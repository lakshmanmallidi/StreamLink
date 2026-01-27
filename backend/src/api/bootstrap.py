"""Bootstrap and migration endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional
import logging
import asyncio

from src.database import get_db, get_database_url, AsyncSessionLocal, engine, Base
from src.models.bootstrap_state import BootstrapState
from src.models.cluster import Cluster
from src.models.service import Service
from src.models.service_dependency import ServiceDependency
from src.utils.crypto import get_crypto_service
from src.config import settings
from kubernetes import client, config
import tempfile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/bootstrap", tags=["Bootstrap"])


class BootstrapStatusResponse(BaseModel):
    """Bootstrap status response."""
    using_sqlite: bool
    postgres_deployed: bool
    keycloak_deployed: bool
    migration_complete: bool
    ready_for_migration: bool


@router.get("/status", response_model=BootstrapStatusResponse)
async def get_bootstrap_status(db: AsyncSession = Depends(get_db)):
    """Get current bootstrap status."""
    using_sqlite = "sqlite" in get_database_url().lower()
    
    if not using_sqlite:
        # Already using Postgres
        return BootstrapStatusResponse(
            using_sqlite=False,
            postgres_deployed=True,
            keycloak_deployed=True,
            migration_complete=True,
            ready_for_migration=False
        )
    
    # Check bootstrap state
    stmt = select(BootstrapState)
    result = await db.execute(stmt)
    bootstrap_state = result.scalar_one_or_none()
    
    if not bootstrap_state:
        return BootstrapStatusResponse(
            using_sqlite=True,
            postgres_deployed=False,
            keycloak_deployed=False,
            migration_complete=False,
            ready_for_migration=False
        )
    
    # Check if Keycloak is deployed (from services table)
    keycloak_stmt = select(Service).where(
        Service.manifest_name == "keycloak",
        Service.is_active == True
    )
    keycloak_result = await db.execute(keycloak_stmt)
    keycloak_deployed = keycloak_result.scalar_one_or_none() is not None
    
    # Check if Postgres pod is ready
    ready_for_migration = False
    if bootstrap_state.postgres_deployed:
        ready_for_migration = await _check_postgres_ready(db)
    
    return BootstrapStatusResponse(
        using_sqlite=True,
        postgres_deployed=bootstrap_state.postgres_deployed,
        keycloak_deployed=keycloak_deployed,
        migration_complete=bootstrap_state.migration_complete,
        ready_for_migration=ready_for_migration
    )


async def _check_postgres_ready(db: AsyncSession) -> bool:
    """Check if Postgres pod is ready using the shared helper."""
    try:
        # Get the cluster (should only be one)
        stmt = select(Cluster).limit(1)
        result = await db.execute(stmt)
        cluster = result.scalar_one_or_none()
        
        if not cluster:
            return False
        
        # Import the shared helper from services
        from src.api.services import _wait_for_pod_ready
        
        # Wait for postgres pod to be ready (with short timeout for status check)
        return await _wait_for_pod_ready(cluster, "postgres", "streamlink", timeout=10)
                
    except Exception as e:
        logger.warning(f"Failed to check Postgres readiness: {e}")
        return False


@router.post("/migrate")
async def migrate_to_postgres(db: AsyncSession = Depends(get_db)):
    """Migrate data from SQLite to Postgres."""
    using_sqlite = "sqlite" in get_database_url().lower()
    
    if not using_sqlite:
        raise HTTPException(status_code=400, detail="Already using Postgres")
    
    # Get bootstrap state
    stmt = select(BootstrapState)
    result = await db.execute(stmt)
    bootstrap_state = result.scalar_one_or_none()
    
    if not bootstrap_state or not bootstrap_state.postgres_deployed:
        raise HTTPException(status_code=400, detail="Postgres not deployed yet")
    
    if bootstrap_state.migration_complete:
        raise HTTPException(status_code=400, detail="Migration already complete")
    
    # Check if Postgres is ready
    if not await _check_postgres_ready(db):
        raise HTTPException(status_code=400, detail="Postgres pod is not ready yet. Please wait a moment and try again.")
    
    try:
        # Get all data from SQLite
        clusters_stmt = select(Cluster)
        clusters_result = await db.execute(clusters_stmt)
        clusters = list(clusters_result.scalars().all())
        
        services_stmt = select(Service)
        services_result = await db.execute(services_stmt)
        services = list(services_result.scalars().all())
        
        dependencies_stmt = select(ServiceDependency)
        dependencies_result = await db.execute(dependencies_stmt)
        dependencies = list(dependencies_result.scalars().all())
        
        logger.info(f"Migrating {len(clusters)} clusters, {len(services)} services, and {len(dependencies)} dependencies to Postgres")
        
        # Get Postgres connection details from bootstrap state
        crypto = get_crypto_service()
        postgres_password = crypto.decrypt(bootstrap_state.postgres_admin_password)
        
        # Backend runs locally, must use external NodePort to connect
        if not bootstrap_state.postgres_external_host:
            raise HTTPException(status_code=500, detail="Postgres external host not found in bootstrap state")
        
        node_ip = bootstrap_state.postgres_external_host
        node_port = bootstrap_state.postgres_external_port or str(settings.POSTGRES_NODEPORT)
        
        # Debug logging
        logger.info(f"Bootstrap state values:")
        logger.info(f"  postgres_external_host: {bootstrap_state.postgres_external_host}")
        logger.info(f"  postgres_external_port: {bootstrap_state.postgres_external_port}")
        logger.info(f"  Using node_ip: {node_ip}")
        logger.info(f"  Using node_port: {node_port}")
        logger.info(f"  Password length: {len(postgres_password) if postgres_password else 0}")
        
        # URL-encode password to handle special characters
        from urllib.parse import quote_plus
        encoded_password = quote_plus(postgres_password)
        
        # Create Postgres URL using external NodePort - connect to streamlink database
        postgres_url = f"postgresql+asyncpg://postgres:{encoded_password}@{node_ip}:{node_port}/streamlink"
        
        logger.info(f"Connecting to Postgres at {node_ip}:{node_port}/streamlink")
        
        # Create new engine for Postgres
        from sqlalchemy.ext.asyncio import create_async_engine
        pg_engine = create_async_engine(postgres_url, echo=False)
        
        # Create tables in Postgres
        async with pg_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        
        # Create session for Postgres
        from sqlalchemy.orm import sessionmaker
        PgSessionLocal = sessionmaker(pg_engine, class_=AsyncSession, expire_on_commit=False)
        
        # Migrate data
        async with PgSessionLocal() as pg_session:
            # Use merge() to copy objects to Postgres (works with detached objects)
            # Migrate bootstrap state
            if bootstrap_state:
                await pg_session.merge(bootstrap_state)
                logger.info("Merged bootstrap_state")
            
            # Migrate clusters
            for cluster in clusters:
                await pg_session.merge(cluster)
            logger.info(f"Merged {len(clusters)} clusters")
            
            # Migrate services
            for service in services:
                await pg_session.merge(service)
            logger.info(f"Merged {len(services)} services")
            
            # Migrate service dependencies
            for dependency in dependencies:
                await pg_session.merge(dependency)
            logger.info(f"Merged {len(dependencies)} dependencies")
            
            await pg_session.commit()
            logger.info("Committed all data to Postgres")
        
        logger.info("Data migrated to Postgres successfully")
        
        # Now mark migration as complete in BOTH databases
        # 1. Update SQLite
        stmt = select(BootstrapState)
        result = await db.execute(stmt)
        bootstrap_state_sqlite = result.scalar_one_or_none()
        if bootstrap_state_sqlite:
            bootstrap_state_sqlite.migration_complete = True
            await db.commit()
            logger.info("Migration flag set to True in SQLite")
        
        # 2. Update Postgres
        async with PgSessionLocal() as pg_session:
            stmt = select(BootstrapState)
            result = await pg_session.execute(stmt)
            bootstrap_state_pg = result.scalar_one_or_none()
            if bootstrap_state_pg:
                bootstrap_state_pg.migration_complete = True
                await pg_session.commit()
                logger.info("Migration flag set to True in Postgres")
        
        logger.info("Migration to Postgres completed successfully")
        
        return {
            "message": "Migration completed successfully. Please restart the backend to connect to Postgres.",
            "clusters_migrated": len(clusters),
            "services_migrated": len(services),
            "dependencies_migrated": len(dependencies),
            "next_step": "Restart backend - it will automatically connect to Postgres"
        }
        
    except Exception as e:
        logger.error(f"Migration failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Migration failed: {str(e)}")
