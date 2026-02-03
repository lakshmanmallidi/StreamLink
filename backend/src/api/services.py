"""Service management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import tempfile
import os
import yaml
import logging
import asyncio

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from src.database import get_db, get_database_url
from src.models.service import Service
from src.models.cluster import Cluster
from src.models.bootstrap_state import BootstrapState
from src.utils.crypto import get_crypto_service
from src.utils.dependencies import dependency_resolver, SERVICE_DISPLAY_NAMES
from src.utils.keycloak_admin import keycloak_admin
from src.api.dependencies import verify_authentication
from src.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/services", tags=["Services"], dependencies=[Depends(verify_authentication)])


class ServiceDeploy(BaseModel):
    cluster_id: str
    name: str
    namespace: Optional[str] = "default"
    config: Optional[dict] = None


class ServiceResponse(BaseModel):
    id: str
    cluster_id: str
    name: str
    manifest_name: Optional[str] = None
    display_name: str
    namespace: str
    status: str
    version: Optional[str]
    replicas: Optional[str]
    last_checked: Optional[datetime]
    is_active: bool
    created_at: datetime


class DeploymentPlanItem(BaseModel):
    """Single item in deployment plan."""
    name: str
    display_name: str
    status: str  # "installed", "will_install"
    order: int


class DeploymentPlanResponse(BaseModel):
    """Response containing deployment plan."""
    target_service: str
    target_display_name: str
    dependencies: List[DeploymentPlanItem]
    total_to_install: int
    message: str


@router.get("", response_model=List[ServiceResponse])
async def list_services(cluster_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """List all deployed services."""
    stmt = select(Service).where(Service.is_active == True)
    if cluster_id:
        stmt = stmt.where(Service.cluster_id == cluster_id)
    
    result = await db.execute(stmt)
    services = result.scalars().all()
    
    return [
        ServiceResponse(
            id=str(service.id),
            cluster_id=str(service.cluster_id),
            name=service.name,
            manifest_name=service.manifest_name,
            display_name=service.display_name,
            namespace=service.namespace,
            status=service.status,
            version=service.version,
            replicas=service.replicas,
            last_checked=service.last_checked,
            is_active=service.is_active,
            created_at=service.created_at
        )
        for service in services
    ]


@router.post("/deployment-plan", response_model=DeploymentPlanResponse)
async def get_deployment_plan(data: ServiceDeploy, db: AsyncSession = Depends(get_db)):
    """
    Get deployment plan showing what services will be installed.
    Shows all dependencies and their current status.
    """
    # Get cluster
    stmt = select(Cluster).where(Cluster.id == data.cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Check if cluster is up
    if cluster.status != "up":
        raise HTTPException(
            status_code=503, 
            detail=f"Cluster is {cluster.status}. Cannot plan deployment when cluster is not running."
        )
    
    # Get all currently installed services for this cluster
    stmt = select(Service).where(
        Service.cluster_id == data.cluster_id,
        Service.is_active == True
    )
    result = await db.execute(stmt)
    installed_services_records = result.scalars().all()
    installed_manifest_names = {svc.manifest_name or svc.name for svc in installed_services_records}
    
    # Get all dependencies for the target service
    all_deps = dependency_resolver.get_all_dependencies(data.name)
    
    # Build deployment plan
    plan_items = []
    to_install_count = 0
    
    for idx, dep_name in enumerate(all_deps):
        is_installed = dep_name in installed_manifest_names
        plan_items.append(DeploymentPlanItem(
            name=dep_name,
            display_name=SERVICE_DISPLAY_NAMES.get(dep_name, dep_name.title()),
            status="installed" if is_installed else "will_install",
            order=idx
        ))
        if not is_installed:
            to_install_count += 1
    
    # Check if target service is already installed by manifest name
    target_already_installed = data.name in installed_manifest_names
    
    if target_already_installed:
        message = f"{SERVICE_DISPLAY_NAMES.get(data.name, data.name)} is already installed."
    elif to_install_count == 0:
        message = f"All dependencies satisfied. Ready to install {SERVICE_DISPLAY_NAMES.get(data.name, data.name)}."
    else:
        message = f"Will install {to_install_count} dependency service(s) before {SERVICE_DISPLAY_NAMES.get(data.name, data.name)}."
    
    return DeploymentPlanResponse(
        target_service=data.name,
        target_display_name=SERVICE_DISPLAY_NAMES.get(data.name, data.name.title()),
        dependencies=plan_items,
        total_to_install=to_install_count,
        message=message
    )


@router.post("", response_model=ServiceResponse)
async def deploy_service(data: ServiceDeploy, db: AsyncSession = Depends(get_db)):
    """Deploy a service to Kubernetes cluster with automatic dependency resolution."""
    # Get cluster
    stmt = select(Cluster).where(Cluster.id == data.cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Check if cluster is up before attempting deployment
    if cluster.status != "up":
        raise HTTPException(
            status_code=503, 
            detail=f"Cluster is {cluster.status}. Cannot deploy service when cluster is not running."
        )
    
    # Get all currently installed services for this cluster
    stmt = select(Service).where(
        Service.cluster_id == data.cluster_id,
        Service.is_active == True
    )
    result = await db.execute(stmt)
    installed_services_records = result.scalars().all()
    installed_manifest_names = {svc.manifest_name or svc.name for svc in installed_services_records}
    
    # Check if service already deployed by manifest name
    if data.name in installed_manifest_names:
        raise HTTPException(status_code=400, detail=f"Service '{data.name}' is already deployed")
    
    # Ensure global ConfigMap exists with latest config from settings
    logger.info(f"Ensuring global ConfigMap before deploying '{data.name}'...")
    try:
        await _ensure_global_config(cluster)  # Always uses streamlink namespace
    except Exception as e:
        logger.error(f"Failed to create ConfigMap: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create global ConfigMap: {str(e)}")

    # Note: Dependency ConfigMaps are created by consumer services (e.g., keycloak) during their deployment.
    # We intentionally avoid creating consumer-specific config during provider (postgres) deployment.
    
    # Get missing dependencies
    missing_deps = dependency_resolver.get_missing_dependencies(data.name, installed_manifest_names)
    
    # Special handling for kafbat-ui: Provision Keycloak client before deployment
    kafbat_client_id = None
    kafbat_client_secret = None
    if data.name == "kafbat-ui":
        try:
            logger.info("Provisioning Keycloak client for Kafbat UI...")
            redirect_uri = settings.KEYCLOAK_KAFBAT_UI_REDIRECT_URI
            kafbat_client_id, kafbat_client_secret = await keycloak_admin.create_client(
                client_id=settings.KEYCLOAK_KAFBAT_UI_CLIENT_ID,
                redirect_uris=[redirect_uri],
                description="Kafbat UI - Kafka Management Interface"
            )
            logger.info(f"Keycloak client created: {kafbat_client_id}")
            
            # Create Kubernetes secret with credentials
            await _create_kafbat_secret(cluster, kafbat_client_secret)
            logger.info("Kubernetes secret created for Kafbat credentials")
            
        except Exception as e:
            error_msg = f"Failed to provision Keycloak for Kafbat UI: {str(e)}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
    
    # Install missing dependencies first (in order)
    for dep_name in missing_deps:
        logger.info(f"Installing dependency: {dep_name}")
        try:
            deployed_name, deployed_namespace, _ = await _deploy_to_kubernetes(cluster, dep_name)
            
            # Create service record for dependency with both deployed name and manifest name
            dep_service = Service(
                cluster_id=data.cluster_id,
                name=deployed_name,
                manifest_name=dep_name,
                display_name=SERVICE_DISPLAY_NAMES.get(dep_name, dep_name.title()),
                namespace=deployed_namespace,
                status="deploying"
            )
            db.add(dep_service)
            await db.commit()
            await db.refresh(dep_service)
            
            logger.info(f"Successfully deployed dependency: {deployed_name} in namespace {deployed_namespace}")
            
            # Wait for pod to be ready before proceeding
            logger.info(f"Waiting for {deployed_name} to be ready...")
            is_ready = await _wait_for_pod_ready(cluster, deployed_name, deployed_namespace)
            
            if is_ready:
                dep_service.status = "running"
                await db.commit()
                logger.info(f"✓ {deployed_name} is ready")
            else:
                dep_service.status = "failed"
                await db.commit()
                raise HTTPException(status_code=500, detail=f"Dependency {dep_name} failed to start")
            
            installed_manifest_names.add(dep_name)
            
        except Exception as e:
            error_msg = f"Failed to deploy dependency '{dep_name}': {str(e)}"
            logger.error(error_msg)
            raise HTTPException(status_code=500, detail=error_msg)
    
    # Now deploy the target service
    try:
        logger.info(f"Deploying target service: {data.name}")
        deployed_name, deployed_namespace, metadata = await _deploy_to_kubernetes(cluster, data.name)
        logger.info(f"Successfully deployed {deployed_name} to Kubernetes in namespace {deployed_namespace}")
    except Exception as e:
        error_msg = f"Failed to deploy {data.name} to Kubernetes: {str(e)}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
    
    # Create service record for target service with both deployed and manifest names
    service = Service(
        cluster_id=data.cluster_id,
        name=deployed_name,
        manifest_name=data.name,
        display_name=SERVICE_DISPLAY_NAMES.get(data.name, data.name.title()),
        namespace=deployed_namespace,
        status="deploying"
    )
    
    db.add(service)
    await db.commit()
    await db.refresh(service)
    
    # Wait for pod to be ready before marking as deployed
    logger.info(f"Waiting for {deployed_name} to be ready...")
    is_ready = await _wait_for_pod_ready(cluster, deployed_name, deployed_namespace)
    
    if is_ready:
        service.status = "running"
        logger.info(f"✓ {deployed_name} is ready")
        
        # For postgres, save credentials to service model after pod is running
        if data.name == "postgres" and metadata.get("postgres_password"):
            from src.database import AsyncSessionLocal
            from sqlalchemy import select as sql_select
            
            crypto = get_crypto_service()
            postgres_password = metadata.get("postgres_password")
            node_ip = metadata.get("node_ip")
            encrypted_password = crypto.encrypt(postgres_password)
            
            # Save credentials to the service record
            service.username = "postgres"
            service.password = encrypted_password
            service.internal_host = "postgres.streamlink.svc.cluster.local"
            service.internal_port = "5432"
            if node_ip:
                service.external_host = node_ip
                service.external_port = str(settings.POSTGRES_NODEPORT)
            
            # Update bootstrap_state to mark postgres as deployed (only the flag)
            if "sqlite" in get_database_url().lower():
                async with AsyncSessionLocal() as session:
                    stmt = sql_select(BootstrapState)
                    result = await session.execute(stmt)
                    bootstrap_state = result.scalar_one_or_none()
                    
                    if not bootstrap_state:
                        bootstrap_state = BootstrapState()
                        session.add(bootstrap_state)
                    
                    bootstrap_state.postgres_deployed = True
                    await session.commit()
            
            logger.info("✓ Postgres is READY - saved credentials to service record")
            logger.info(f"  Internal: postgres.streamlink.svc.cluster.local:5432")
            if node_ip:
                logger.info(f"  External: {node_ip}:{settings.POSTGRES_NODEPORT}")
        
        # For keycloak, save credentials to service model after pod is running
        elif data.name == "keycloak" and metadata.get("keycloak_admin_password"):
            crypto = get_crypto_service()
            keycloak_admin_password = metadata.get("keycloak_admin_password")
            node_ip = metadata.get("node_ip")
            encrypted_password = crypto.encrypt(keycloak_admin_password)
            
            # Save credentials and config to the service record
            service.username = "admin"
            service.password = encrypted_password
            service.internal_host = "keycloak.streamlink.svc.cluster.local"
            service.internal_port = "8080"
            if node_ip:
                service.external_host = node_ip
                service.external_port = str(settings.KEYCLOAK_NODEPORT)
                
                # Store external URL in config for auth endpoints
                import json
                external_url = f"http://{node_ip}:{settings.KEYCLOAK_NODEPORT}"
                service.config = json.dumps({"external_url": external_url})
            
            logger.info("✓ Keycloak is READY - saved credentials to service record")
            logger.info(f"  Internal: keycloak.streamlink.svc.cluster.local:8080")
            if node_ip:
                logger.info(f"  External: {node_ip}:{settings.KEYCLOAK_NODEPORT}")
    else:
        service.status = "failed"
        logger.error(f"✗ {deployed_name} failed to become ready")
        raise HTTPException(status_code=500, detail=f"Service {data.name} failed to start")
    
    await db.commit()
    
    # Special handling for keycloak: Initialize realm after deployment
    if data.name == "keycloak":
        try:
            logger.info("Waiting for Keycloak to be ready before initializing realm...")
            import asyncio
            await asyncio.sleep(30)  # Wait for Keycloak to start up
            
            logger.info("Initializing Keycloak realm...")
            from src.utils.keycloak_admin import KeycloakAdmin
            from src.models.oauth_client import OAuthClient
            import json
            
            # Create temporary KeycloakAdmin instance using stored credentials
            # Use external_host for connections from outside the cluster
            keycloak_temp = KeycloakAdmin()
            keycloak_url = f"http://{service.external_host}:{service.external_port}" if service.external_host else "http://keycloak.streamlink.svc.cluster.local:8080"
            keycloak_temp.base_url = keycloak_url
            crypto = get_crypto_service()
            try:
                admin_password = crypto.decrypt(service.password) if service.password else ""
            except Exception:
                admin_password = ""
            keycloak_temp.admin_password = admin_password
            logger.info(f"Using Keycloak URL: {keycloak_url}")
            
            # Create the streamlink realm
            await keycloak_temp.create_realm("streamlink", "StreamLink Platform")
            logger.info("Keycloak realm 'streamlink' created successfully")
            
            # Update keycloak instance to use new realm
            keycloak_temp.realm = "streamlink"
            
            # Create streamlink-api client with redirect URI from config
            api_client_id, api_client_secret = await keycloak_temp.create_client(
                client_id=settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID,
                redirect_uris=[settings.KEYCLOAK_STREAMLINK_API_REDIRECT_URI],
                post_logout_uris=[settings.KEYCLOAK_STREAMLINK_API_POST_LOGOUT_URI],
                description="StreamLink API Client"
            )
            logger.info(f"Created Keycloak client: {api_client_id}")
            
            # Store client credentials in database (encrypted)
            encrypted_secret = crypto.encrypt(api_client_secret)
            oauth_client = OAuthClient(
                client_id=api_client_id,
                client_secret=encrypted_secret,
                realm="streamlink",
                redirect_uris=json.dumps([settings.KEYCLOAK_STREAMLINK_API_REDIRECT_URI]),
                description="StreamLink API Client",
                is_active=True
            )
            db.add(oauth_client)
            await db.commit()
            logger.info(f"✓ Stored OAuth client '{api_client_id}' credentials in database (encrypted)")
            
            # Mark Keycloak as deployed in bootstrap state (works for both SQLite and Postgres)
            stmt = select(BootstrapState)
            result = await db.execute(stmt)
            bootstrap_state = result.scalar_one_or_none()
            
            if not bootstrap_state:
                bootstrap_state = BootstrapState()
                db.add(bootstrap_state)
            
            bootstrap_state.keycloak_deployed = True
            await db.commit()
            logger.info("✓ Marked Keycloak as deployed in bootstrap state - OAuth authentication is now active")
            
        except Exception as e:
            logger.warning(f"Failed to initialize Keycloak realm (you can do this manually later): {str(e)}")
            import traceback
            traceback.print_exc()
    
    logger.info(f"Service {service.name} and all dependencies deployed successfully.")
    
    return ServiceResponse(
        id=str(service.id),
        cluster_id=str(service.cluster_id),
        name=service.name,
        display_name=service.display_name,
        namespace=service.namespace,
        status=service.status,
        version=service.version,
        replicas=service.replicas,
        last_checked=service.last_checked,
        is_active=service.is_active,
        created_at=service.created_at
    )


@router.get("/{service_id}/delete-plan")
async def get_delete_plan(service_id: str, db: AsyncSession = Depends(get_db)):
    """Get list of services that will be deleted (including dependents)."""
    stmt = select(Service).where(Service.id == service_id)
    result = await db.execute(stmt)
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    # Get all active services in the same cluster
    stmt = select(Service).where(
        Service.cluster_id == service.cluster_id,
        Service.is_active == True
    )
    result = await db.execute(stmt)
    all_services = result.scalars().all()
    
    # Build a map of manifest names to service info
    service_map = {svc.manifest_name or svc.name: svc for svc in all_services}
    
    # Find all services that depend on this service
    target_manifest_name = service.manifest_name or service.name
    dependent_services = []
    
    for svc in all_services:
        svc_manifest = svc.manifest_name or svc.name
        if svc_manifest == target_manifest_name:
            continue
        
        # Check if this service depends on the target
        deps = dependency_resolver.get_all_dependencies(svc_manifest)
        if target_manifest_name in deps:
            dependent_services.append({
                "id": str(svc.id),
                "name": svc.name,
                "manifest_name": svc.manifest_name,
                "display_name": svc.display_name,
                "namespace": svc.namespace
            })
    
    return {
        "target": {
            "id": str(service.id),
            "name": service.name,
            "manifest_name": service.manifest_name,
            "display_name": service.display_name,
            "namespace": service.namespace
        },
        "dependents": dependent_services,
        "total_deletions": len(dependent_services) + 1
    }


@router.delete("/{service_id}")
async def delete_service(service_id: str, cascade: bool = False, db: AsyncSession = Depends(get_db)):
    """Delete a service from Kubernetes cluster. If cascade=True, deletes dependents too."""
    stmt = select(Service).where(Service.id == service_id)
    result = await db.execute(stmt)
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    # Get all active services in the same cluster
    stmt = select(Service).where(
        Service.cluster_id == service.cluster_id,
        Service.is_active == True
    )
    result = await db.execute(stmt)
    all_services = result.scalars().all()
    
    # Find dependent services
    target_manifest_name = service.manifest_name or service.name
    dependent_services = []
    
    for svc in all_services:
        svc_manifest = svc.manifest_name or svc.name
        if svc_manifest == target_manifest_name:
            continue
        
        # Check if this service depends on the target
        deps = dependency_resolver.get_all_dependencies(svc_manifest)
        if target_manifest_name in deps:
            dependent_services.append(svc)
    
    # If there are dependents and cascade is not enabled, return error
    if dependent_services and not cascade:
        dependent_names = [svc.display_name for svc in dependent_services]
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot delete {service.display_name}. The following services depend on it: {', '.join(dependent_names)}. Use cascade=true to delete all."
        )
    
    # Get cluster
    stmt = select(Cluster).where(Cluster.id == service.cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    deleted_services = []
    
    # STEP 1: Update database first (before K8s deletion)
    # Delete dependent services from database first
    if cascade and dependent_services:
        logger.info(f"Cascading delete: marking {len(dependent_services)} dependent service(s) as deleted in database")
        for dep_svc in dependent_services:
            dep_svc.is_active = False
            dep_svc.status = "deleted"
            deleted_services.append(dep_svc.display_name)
    
    # Mark target service as deleted in database
    service.is_active = False
    service.status = "deleted"
    deleted_services.append(service.display_name)
    
    # Special handling for postgres: Delete bootstrap_state and update services table in SQLite
    if service.manifest_name == "postgres":
        logger.info("Postgres service deleted - cleaning up SQLite database")
        
        # Connect directly to SQLite to clean up
        import sqlite3
        db_path = os.path.join(os.path.dirname(__file__), "..", "..", "bootstrap.db")
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # Delete bootstrap_state
            cursor.execute("DELETE FROM bootstrap_state")
            logger.info("Deleted bootstrap_state from SQLite")
            
            # Mark postgres service as deleted in services table
            cursor.execute("""
                UPDATE services 
                SET is_active = 0, status = 'deleted' 
                WHERE manifest_name = 'postgres'
            """)
            logger.info("Marked postgres service as deleted in SQLite services table")
            
            conn.commit()
            conn.close()
            logger.info("SQLite cleanup complete - backend will use SQLite on restart")
        except Exception as e:
            logger.error(f"Failed to clean up SQLite: {e}")
            # Continue anyway - worst case user needs to delete bootstrap.db manually
    
    # Commit database changes first
    await db.commit()
    logger.info("Database updated - services marked as deleted")
    
    # STEP 2: Now delete from Kubernetes (if this fails, database is already updated)
    # Delete dependent services from Kubernetes
    if cascade and dependent_services:
        logger.info(f"Deleting {len(dependent_services)} dependent service(s) from Kubernetes")
        for dep_svc in dependent_services:
            if cluster:
                try:
                    logger.info(f"Deleting dependent service '{dep_svc.name}' from namespace '{dep_svc.namespace}'")
                    await _delete_from_kubernetes(cluster, dep_svc)
                    logger.info(f"Successfully deleted dependent service '{dep_svc.name}'")
                except Exception as e:
                    logger.error(f"Failed to delete dependent service from K8s: {type(e).__name__}: {e}")
    
    # Delete the target service from Kubernetes
    if cluster:
        try:
            logger.info(f"Attempting to delete service '{service.name}' from namespace '{service.namespace}'")
            await _delete_from_kubernetes(cluster, service)
            logger.info(f"Successfully deleted service '{service.name}' from Kubernetes")
            
            # Special handling for kafbat-ui: Delete Keycloak client
            if service.manifest_name == "kafbat-ui":
                try:
                    logger.info(f"Deleting Keycloak client: {settings.KEYCLOAK_KAFBAT_UI_CLIENT_ID}")
                    deleted = await keycloak_admin.delete_client(settings.KEYCLOAK_KAFBAT_UI_CLIENT_ID)
                    if deleted:
                        logger.info(f"Keycloak client deleted: {settings.KEYCLOAK_KAFBAT_UI_CLIENT_ID}")
                    else:
                        logger.warning(f"Keycloak client not found: {settings.KEYCLOAK_KAFBAT_UI_CLIENT_ID}")
                    
                    # Delete Kubernetes secret
                    logger.info("Deleting Kubernetes secret for Kafbat credentials...")
                    await _delete_kafbat_secret(cluster)
                    logger.info("Kubernetes secret deleted")
                    
                except Exception as e:
                    logger.error(f"Keycloak cleanup failed: {type(e).__name__}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    # Don't fail the delete operation if Keycloak cleanup fails
            
            # Special handling for keycloak: Delete OAuth clients from database and reset bootstrap flag
            if service.manifest_name == "keycloak":
                try:
                    from src.models.oauth_client import OAuthClient
                    logger.info("Cleaning up Keycloak OAuth clients from database...")
                    
                    # Delete all OAuth clients
                    stmt = select(OAuthClient)
                    result = await db.execute(stmt)
                    oauth_clients = result.scalars().all()
                    
                    for client in oauth_clients:
                        await db.delete(client)
                        logger.info(f"Deleted OAuth client: {client.client_id}")
                    
                    # Reset keycloak_deployed flag in bootstrap_state
                    stmt = select(BootstrapState)
                    result = await db.execute(stmt)
                    bootstrap_state = result.scalar_one_or_none()
                    
                    if bootstrap_state:
                        bootstrap_state.keycloak_deployed = False
                        logger.info("Reset keycloak_deployed flag in bootstrap_state")
                    
                    await db.commit()
                    logger.info("Keycloak cleanup completed - OAuth authentication disabled")
                    
                except Exception as e:
                    logger.error(f"Keycloak database cleanup failed: {type(e).__name__}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    # Don't fail the delete operation
                    
        except Exception as e:
            logger.error(f"Failed to delete from Kubernetes: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            # Don't raise - database is already updated
    else:
        logger.warning(f"No cluster found for service {service.id}, skipping Kubernetes deletion")
    
    # Prepare response with restart warning for postgres
    if service.manifest_name == "postgres":
        return {
            "message": "Postgres deleted successfully. ⚠️ RESTART REQUIRED: Please restart the backend immediately to switch to SQLite.",
            "deleted_services": deleted_services,
            "restart_required": True,
            "warning": "Backend will fail with connection errors until restarted"
        }
    
    if len(deleted_services) > 1:
        return {
            "message": f"Successfully deleted {len(deleted_services)} services",
            "deleted_services": deleted_services
        }
    else:
        return {"message": "Service deleted successfully"}


@router.post("/{service_id}/check-status")
async def check_service_status(service_id: str, db: AsyncSession = Depends(get_db)):
    """Check service status in Kubernetes."""
    logger.debug(f"check_service_status called for service_id: {service_id}")
    stmt = select(Service).where(Service.id == service_id)
    result = await db.execute(stmt)
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    # Get cluster
    stmt = select(Cluster).where(Cluster.id == service.cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Check status in Kubernetes
    try:
        status_info = await _check_kubernetes_status(cluster, service)
        service.status = status_info["status"]
        service.replicas = status_info.get("replicas")
        service.last_checked = datetime.utcnow()
    except Exception as e:
        service.status = "unknown"
        service.last_checked = datetime.utcnow()
    
    await db.commit()
    
    return {
        "status": service.status,
        "replicas": service.replicas,
        "last_checked": service.last_checked
    }


async def _wait_for_pod_ready(cluster: Cluster, service_name: str, namespace: str = "streamlink", timeout: int = 300):
    """Wait for pod to be in Running state with all containers ready.
    Returns True if ready, False if timeout.
    """
    import time
    from src.utils.kubernetes import kube_config_context
    
    start_time = time.time()
    logger.info(f"Waiting for {service_name} pod to be ready (timeout: {timeout}s)...")
    
    with kube_config_context(cluster):
        core_v1 = client.CoreV1Api()
        
        while (time.time() - start_time) < timeout:
            try:
                # List pods with label selector
                pods = core_v1.list_namespaced_pod(
                    namespace=namespace,
                    label_selector=f"app={service_name}"
                )
                
                if not pods.items:
                    logger.debug(f"No pods found for {service_name}, waiting...")
                    await asyncio.sleep(5)
                    continue
                
                pod = pods.items[0]
                
                # Check pod phase
                if pod.status.phase == "Running":
                    # Check if all containers are ready
                    all_ready = True
                    if pod.status.container_statuses:
                        for container in pod.status.container_statuses:
                            if not container.ready:
                                all_ready = False
                                break
                    
                    if all_ready:
                        logger.info(f"✓ {service_name} pod is ready")
                        return True
                    else:
                        logger.debug(f"{service_name} pod is Running but containers not ready yet")
                elif pod.status.phase in ["Failed", "Unknown"]:
                    logger.error(f"{service_name} pod is in {pod.status.phase} state")
                    return False
                else:
                    logger.debug(f"{service_name} pod phase: {pod.status.phase}")
                
            except ApiException as e:
                if e.status != 404:
                    logger.warning(f"Error checking pod status: {e}")
            
            await asyncio.sleep(5)
        
        logger.warning(f"Timeout waiting for {service_name} pod to be ready")
        return False


async def _deploy_to_kubernetes(cluster: Cluster, service_name: str) -> tuple[str, str, dict]:
    """Deploy service to Kubernetes cluster using YAML manifest.
    Returns (deployed_name, deployed_namespace, metadata) tuple.
    metadata contains service-specific data like passwords, endpoints, etc.
    """
    import secrets
    import string
    from sqlalchemy import select as sql_select
    from src.models.bootstrap_state import BootstrapState
    from src.utils.kubernetes import kube_config_context
    
    crypto = get_crypto_service()
    deployed_namespace = None
    deployed_name = None
    
    with kube_config_context(cluster):
        # Load YAML manifest for the service
        manifest_path = os.path.join(
            os.path.dirname(__file__), 
            '..', '..', 
            'deployments', 
            f'{service_name}.yaml'
        )
        
        if not os.path.exists(manifest_path):
            raise ValueError(f"Deployment manifest not found: {manifest_path}")
        
        # Read and apply the YAML manifest
        with open(manifest_path, 'r') as f:
            manifest_content = f.read()
        
        # No more string replacements - NodePorts come from ConfigMap
        
        # Special handling for postgres and keycloak - generate passwords and create secrets
        postgres_password = None
        keycloak_admin_password = None
        keycloak_client_secret = None
        
        if service_name == "postgres":
            logger.info("Generating password for Postgres deployment")
            alphabet = string.ascii_letters + string.digits + string.punctuation
            postgres_password = ''.join(secrets.choice(alphabet) for _ in range(32))
            
            # Create Kubernetes Secret for Postgres
            core_v1 = client.CoreV1Api()
            secret = client.V1Secret(
                metadata=client.V1ObjectMeta(name="postgres-secret", namespace="streamlink"),
                string_data={
                    "postgres-password": postgres_password
                }
            )
            
            try:
                core_v1.create_namespaced_secret(namespace="streamlink", body=secret)
                logger.info("✓ Created Kubernetes Secret 'postgres-secret'")
            except ApiException as e:
                if e.status == 409:  # Already exists, update it
                    core_v1.patch_namespaced_secret(name="postgres-secret", namespace="streamlink", body=secret)
                    logger.info("✓ Updated Kubernetes Secret 'postgres-secret'")
                else:
                    raise
            
        elif service_name == "keycloak":
            logger.info("Generating admin password for Keycloak deployment")
            # Use a safe alphabet that avoids shell/SQL-breaking characters (' " \ $)
            safe_punct = "@#%+=-_.:,;!?"  # excludes quotes, backslash, dollar
            alphabet = string.ascii_letters + string.digits + safe_punct
            keycloak_admin_password = ''.join(secrets.choice(alphabet) for _ in range(32))
            
            core_v1 = client.CoreV1Api()
            
            # 1) Ensure Keycloak admin secret
            admin_secret = client.V1Secret(
                metadata=client.V1ObjectMeta(name="keycloak-secret", namespace="streamlink"),
                string_data={
                    "admin-password": keycloak_admin_password
                }
            )
            try:
                core_v1.create_namespaced_secret(namespace="streamlink", body=admin_secret)
                logger.info("✓ Created Kubernetes Secret 'keycloak-secret'")
            except ApiException as e:
                if e.status == 409:
                    core_v1.patch_namespaced_secret(name="keycloak-secret", namespace="streamlink", body=admin_secret)
                    logger.info("✓ Updated Kubernetes Secret 'keycloak-secret'")
                else:
                    raise

            # 2) Create dependency secrets for consumers (postgres superuser password for init)
            # Read postgres password from existing secret (preferred) or DB service record
            pg_root_password = ""
            try:
                existing_pg = core_v1.read_namespaced_secret(name="postgres-secret", namespace="streamlink")
                if getattr(existing_pg, 'data', None) and existing_pg.data.get("postgres-password"):
                    import base64
                    pg_root_password = base64.b64decode(existing_pg.data["postgres-password"]).decode("utf-8")
            except ApiException:
                pass
            if not pg_root_password:
                from src.database import AsyncSessionLocal
                async with AsyncSessionLocal() as session:
                    res = await session.execute(select(Service).where(Service.manifest_name=="postgres", Service.cluster_id==cluster.id, Service.is_active==True))
                    pg_service = res.scalar_one_or_none()
                    if pg_service and pg_service.password:
                        crypto_local = get_crypto_service()
                        try:
                            pg_root_password = crypto_local.decrypt(pg_service.password)
                        except Exception:
                            pg_root_password = ""

            deps_secret = client.V1Secret(
                metadata=client.V1ObjectMeta(name="streamlink-deps-secrets", namespace="streamlink"),
                string_data={
                    "postgres_password": pg_root_password
                }
            )
            try:
                core_v1.create_namespaced_secret(namespace="streamlink", body=deps_secret)
                logger.info("✓ Created Kubernetes Secret 'streamlink-deps-secrets'")
            except ApiException as e:
                if e.status == 409:
                    core_v1.patch_namespaced_secret(name="streamlink-deps-secrets", namespace="streamlink", body=deps_secret)
                    logger.info("✓ Updated Kubernetes Secret 'streamlink-deps-secrets'")
                else:
                    raise

            # 3) Ensure dependency ConfigMap with Postgres internal host/port and JDBC URL
            # Try to read postgres secret to ensure connectivity; if missing, recreate from DB service
            try:
                core_v1.read_namespaced_secret(name="postgres-secret", namespace="streamlink")
            except ApiException as e:
                if e.status == 404:
                    logger.info("postgres-secret missing; attempting to recreate from DB service record")
                    from src.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as session:
                        res = await session.execute(select(Service).where(Service.manifest_name=="postgres", Service.cluster_id==cluster.id, Service.is_active==True))
                        pg_service = res.scalar_one_or_none()
                        if pg_service and pg_service.password:
                            crypto_local = get_crypto_service()
                            try:
                                pg_password_plain = crypto_local.decrypt(pg_service.password)
                            except Exception:
                                pg_password_plain = ""
                            if pg_password_plain:
                                pg_secret = client.V1Secret(
                                    metadata=client.V1ObjectMeta(name="postgres-secret", namespace="streamlink"),
                                    string_data={"postgres-password": pg_password_plain}
                                )
                                try:
                                    core_v1.create_namespaced_secret(namespace="streamlink", body=pg_secret)
                                    logger.info("✓ Recreated 'postgres-secret' from DB")
                                except ApiException as e2:
                                    if e2.status == 409:
                                        core_v1.patch_namespaced_secret(name="postgres-secret", namespace="streamlink", body=pg_secret)
                                        logger.info("✓ Updated 'postgres-secret' from DB")
                                    else:
                                        raise
                        else:
                            logger.warning("Postgres service record not found or no password stored; proceeding")
                else:
                    raise

            # Build ConfigMap data (only internal host per spec)
            postgres_host = "postgres.streamlink.svc.cluster.local"
            from src.database import AsyncSessionLocal
            async with AsyncSessionLocal() as session:
                res = await session.execute(select(Service).where(Service.manifest_name=="postgres", Service.cluster_id==cluster.id, Service.is_active==True))
                pg_service = res.scalar_one_or_none()
                if pg_service:
                    postgres_host = pg_service.internal_host or postgres_host

            deps_config = client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name="streamlink-deps", namespace="streamlink"),
                data={
                    "postgres_internal_host": postgres_host
                }
            )
            try:
                core_v1.create_namespaced_config_map(namespace="streamlink", body=deps_config)
                logger.info("✓ Created ConfigMap 'streamlink-deps'")
            except ApiException as e:
                if e.status == 409:
                    core_v1.replace_namespaced_config_map(name="streamlink-deps", namespace="streamlink", body=deps_config)
                    logger.info("✓ Updated ConfigMap 'streamlink-deps'")
                else:
                    raise

            # 4) Run init Job to create keycloak user and database
            from kubernetes.client import V1EnvVar
            job_manifest = {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {"name": "keycloak-db-init", "namespace": "streamlink"},
                "spec": {
                    "backoffLimit": 2,
                    "template": {
                        "metadata": {"labels": {"app": "keycloak-db-init"}},
                        "spec": {
                            "restartPolicy": "Never",
                            "containers": [
                                {
                                    "name": "psql",
                                    "image": "postgres:15-alpine",
                                    "env": [
                                        {"name": "POSTGRES_HOST", "valueFrom": {"configMapKeyRef": {"name": "streamlink-deps", "key": "postgres_internal_host"}}},
                                        {"name": "PGPASSWORD", "valueFrom": {"secretKeyRef": {"name": "streamlink-deps-secrets", "key": "postgres_password"}}},
                                        {"name": "KEYCLOAK_DB_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "keycloak-secret", "key": "admin-password"}}}
                                    ],
                                    "command": ["sh","-c"],
                                    "args": [
                                        "ESC_PWD=$(printf %s \"$KEYCLOAK_DB_PASSWORD\" | sed \"s/'/''/g\"); DB_EXISTS=$(psql -h \"$POSTGRES_HOST\" -U postgres -d postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='keycloak'\"); if [ \"$DB_EXISTS\" = \"1\" ]; then echo 'Dropping existing keycloak database to reset with new password...'; psql -h \"$POSTGRES_HOST\" -U postgres -d postgres -v ON_ERROR_STOP=1 -c \"DROP DATABASE keycloak\"; fi; ROLE_EXISTS=$(psql -h \"$POSTGRES_HOST\" -U postgres -d postgres -tAc \"SELECT 1 FROM pg_roles WHERE rolname='keycloak'\"); if [ \"$ROLE_EXISTS\" != \"1\" ]; then psql -h \"$POSTGRES_HOST\" -U postgres -d postgres -v ON_ERROR_STOP=1 -c \"CREATE USER keycloak WITH PASSWORD '$ESC_PWD'\"; else psql -h \"$POSTGRES_HOST\" -U postgres -d postgres -v ON_ERROR_STOP=1 -c \"ALTER USER keycloak WITH PASSWORD '$ESC_PWD'\"; fi; psql -h \"$POSTGRES_HOST\" -U postgres -d postgres -v ON_ERROR_STOP=1 -c \"CREATE DATABASE keycloak OWNER keycloak\""
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
            from kubernetes import utils as k8s_utils
            from kubernetes.client import BatchV1Api
            k8s_client = client.ApiClient()
            batch_v1 = BatchV1Api()

            # Ensure idempotency: delete existing job if present, wait for deletion
            try:
                batch_v1.read_namespaced_job(name="keycloak-db-init", namespace="streamlink")
                logger.info("Existing Job 'keycloak-db-init' found; deleting before recreate")
                batch_v1.delete_namespaced_job(name="keycloak-db-init", namespace="streamlink", propagation_policy="Foreground")
                import time
                start_del = time.time()
                while time.time() - start_del < 60:
                    try:
                        batch_v1.read_namespaced_job(name="keycloak-db-init", namespace="streamlink")
                        time.sleep(2)
                    except ApiException as e:
                        if e.status == 404:
                            break
                        else:
                            raise
            except ApiException as e:
                if e.status != 404:
                    raise

            # Create Job
            k8s_utils.create_from_dict(k8s_client, job_manifest)
            logger.info("✓ Created Job 'keycloak-db-init'")

            # Wait for job completion
            from kubernetes.client import BatchV1Api
            batch_v1 = BatchV1Api()
            import time
            start = time.time()
            while time.time() - start < 180:
                job = batch_v1.read_namespaced_job(name="keycloak-db-init", namespace="streamlink")
                if job.status.succeeded and job.status.succeeded >= 1:
                    logger.info("✓ Keycloak DB init job succeeded")
                    break
                if job.status.failed and job.status.failed >= 1:
                    logger.error("✗ Keycloak DB init job failed")
                    raise RuntimeError("Keycloak DB initialization failed")
                await asyncio.sleep(5)
            
            # Clean up the job after completion
            try:
                batch_v1.delete_namespaced_job(name="keycloak-db-init", namespace="streamlink", propagation_policy="Background")
                logger.info("✓ Deleted Job 'keycloak-db-init' after completion")
            except ApiException as e:
                if e.status != 404:
                    logger.warning(f"Failed to delete Job 'keycloak-db-init': {e}")

        
        # Apply the manifest using kubectl-like approach - respect namespace from YAML
        from kubernetes import utils
        k8s_client = client.ApiClient()
        
        # Parse and apply each document in the YAML
        for doc in yaml.safe_load_all(manifest_content):
            if doc is None:
                continue
            
            kind = doc.get('kind')
            api_version = doc.get('apiVersion')
            
            # Capture the namespace and name from the YAML
            if 'metadata' in doc:
                if 'namespace' in doc['metadata']:
                    deployed_namespace = doc['metadata']['namespace']
                # Capture the actual deployed name from Deployment/StatefulSet resources
                if kind in ['Deployment', 'StatefulSet'] and 'name' in doc['metadata']:
                    deployed_name = doc['metadata']['name']

            # No dynamic env injection; YAML consumes ConfigMap and Secrets directly
            
            # Apply based on resource type
            if kind == "Namespace":
                core_v1 = client.CoreV1Api()
                try:
                    core_v1.create_namespace(body=doc)
                except ApiException as e:
                    if e.status != 409:  # Ignore if already exists
                        raise
            elif kind == "PersistentVolumeClaim":
                core_v1 = client.CoreV1Api()
                try:
                    core_v1.create_namespaced_persistent_volume_claim(
                        namespace=doc['metadata']['namespace'],
                        body=doc
                    )
                except ApiException as e:
                    if e.status == 409:  # Already exists, update instead
                        core_v1.patch_namespaced_persistent_volume_claim(
                            name=doc['metadata']['name'],
                            namespace=doc['metadata']['namespace'],
                            body=doc
                        )
                    else:
                        raise
            elif kind == "StatefulSet":
                apps_v1 = client.AppsV1Api()
                try:
                    apps_v1.create_namespaced_stateful_set(
                        namespace=doc['metadata']['namespace'],
                        body=doc
                    )
                except ApiException as e:
                    if e.status == 409:  # Already exists, update instead
                        apps_v1.patch_namespaced_stateful_set(
                            name=doc['metadata']['name'],
                            namespace=doc['metadata']['namespace'],
                            body=doc
                        )
                    else:
                        raise
            elif kind == "Deployment":
                apps_v1 = client.AppsV1Api()
                try:
                    apps_v1.create_namespaced_deployment(
                        namespace=doc['metadata']['namespace'],
                        body=doc
                    )
                except ApiException as e:
                    if e.status == 409:  # Already exists, update instead
                        apps_v1.patch_namespaced_deployment(
                            name=doc['metadata']['name'],
                            namespace=doc['metadata']['namespace'],
                            body=doc
                        )
                    else:
                        raise
            elif kind == "Service":
                core_v1 = client.CoreV1Api()
                try:
                    core_v1.create_namespaced_service(
                        namespace=doc['metadata']['namespace'],
                        body=doc
                    )
                except ApiException as e:
                    if e.status == 409:  # Already exists, update instead
                        core_v1.patch_namespaced_service(
                            name=doc['metadata']['name'],
                            namespace=doc['metadata']['namespace'],
                            body=doc
                        )
                    else:
                        raise
    
    # Save passwords and endpoints to bootstrap state
    from src.database import AsyncSessionLocal, get_database_url
    
    async with AsyncSessionLocal() as session:
        stmt = sql_select(BootstrapState)
        result = await session.execute(stmt)
        bootstrap_state = result.scalar_one_or_none()
        
        if not bootstrap_state:
            bootstrap_state = BootstrapState()
            session.add(bootstrap_state)
        
        # Get node IP for external access
        from src.utils.kubernetes import get_node_ip
        node_ip = get_node_ip(cluster)
        if not node_ip:
            logger.warning("Could not get node IP")
        
        # Prepare metadata to return (will be saved after pod is ready)
        metadata = {}
        
        if service_name == "postgres" and postgres_password:
            metadata["postgres_password"] = postgres_password
            metadata["node_ip"] = node_ip
            
        elif service_name == "keycloak" and keycloak_admin_password:
            # Pass admin password and node info via metadata; actual DB save occurs after pod is ready
            metadata["keycloak_admin_password"] = keycloak_admin_password
            metadata["node_ip"] = node_ip
        
        await session.commit()
    
    return deployed_name or service_name, deployed_namespace or "streamlink", metadata


async def _delete_from_kubernetes(cluster: Cluster, service: Service):
    """Delete service from Kubernetes cluster.
    Deletes all related resources: Deployment/StatefulSet, Services, PVCs, and Secrets.
    """
    from src.utils.kubernetes import kube_config_context
    
    with kube_config_context(cluster):
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        service_name = service.name
        namespace = service.namespace
        
        logger.info(f"Deleting all resources for '{service_name}' from namespace '{namespace}'")
        
        # 1. Delete Deployment or StatefulSet
        logger.info(f"Deleting deployment/statefulset '{service_name}'")
        try:
            apps_v1.delete_namespaced_deployment(
                name=service_name,
                namespace=namespace,
                propagation_policy='Foreground'
            )
            logger.info(f"✓ Deployment '{service_name}' deletion initiated")
        except ApiException as e:
            if e.status == 404:
                # Not a deployment, try statefulset
                try:
                    apps_v1.delete_namespaced_stateful_set(
                        name=service_name,
                        namespace=namespace,
                        propagation_policy='Foreground'
                    )
                    logger.info(f"✓ StatefulSet '{service_name}' deletion initiated")
                except ApiException as e2:
                    if e2.status == 404:
                        logger.debug(f"Deployment/StatefulSet '{service_name}' not found")
                    else:
                        raise
            else:
                raise
        
        # 2. Delete ClusterIP Service
        logger.info(f"Deleting service '{service_name}'")
        try:
            core_v1.delete_namespaced_service(
                name=service_name,
                namespace=namespace
            )
            logger.info(f"✓ Service '{service_name}' deletion initiated")
        except ApiException as e:
            if e.status == 404:
                logger.debug(f"Service '{service_name}' not found")
            else:
                raise
        
        # 3. Delete External Service (NodePort) - common pattern: {service}-external
        external_service_name = f"{service_name}-external"
        logger.info(f"Deleting external service '{external_service_name}'")
        try:
            core_v1.delete_namespaced_service(
                name=external_service_name,
                namespace=namespace
            )
            logger.info(f"✓ Service '{external_service_name}' deletion initiated")
        except ApiException as e:
            if e.status == 404:
                logger.debug(f"External service '{external_service_name}' not found")
            else:
                logger.warning(f"Failed to delete external service: {e}")
        
        # 4. Delete PersistentVolumeClaim - common pattern: {service}-pvc
        pvc_name = f"{service_name}-pvc"
        logger.info(f"Deleting PVC '{pvc_name}'")
        try:
            core_v1.delete_namespaced_persistent_volume_claim(
                name=pvc_name,
                namespace=namespace
            )
            logger.info(f"✓ PVC '{pvc_name}' deletion initiated")
        except ApiException as e:
            if e.status == 404:
                logger.debug(f"PVC '{pvc_name}' not found")
            else:
                logger.warning(f"Failed to delete PVC: {e}")
        
        # 5. Delete Secret - common pattern: {service}-secret
        secret_name = f"{service_name}-secret"
        logger.info(f"Deleting secret '{secret_name}'")
        try:
            core_v1.delete_namespaced_secret(
                name=secret_name,
                namespace=namespace
            )
            logger.info(f"✓ Secret '{secret_name}' deletion initiated")
        except ApiException as e:
            if e.status == 404:
                logger.debug(f"Secret '{secret_name}' not found")
            else:
                logger.warning(f"Failed to delete secret: {e}")
        
        logger.info(f"✓ All resources for '{service_name}' deleted successfully")


async def _check_kubernetes_status(cluster: Cluster, service: Service):
    """Check service status in Kubernetes by examining pod health."""
    from src.utils.kubernetes import kube_config_context
    
    logger.debug(f"Checking status for service: {service.name} in namespace: {service.namespace}")
    
    with kube_config_context(cluster):
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        # Get deployment or statefulset status
        desired_replicas = 0
        available_replicas = 0
        
        # Try deployment first
        try:
            deployment = apps_v1.read_namespaced_deployment(
                name=service.name,
                namespace=service.namespace
            )
            desired_replicas = deployment.spec.replicas or 0
            available_replicas = deployment.status.available_replicas or 0
        except ApiException as e:
            if e.status == 404:
                # Not a deployment, try statefulset
                try:
                    statefulset = apps_v1.read_namespaced_stateful_set(
                        name=service.name,
                        namespace=service.namespace
                    )
                    desired_replicas = statefulset.spec.replicas or 0
                    available_replicas = statefulset.status.ready_replicas or 0
                except ApiException as e2:
                    if e2.status == 404:
                        return {"status": "not_found", "replicas": "0/0"}
                    raise
            else:
                raise
        
        # Get pod status for more detailed information
        try:
            pods = core_v1.list_namespaced_pod(
                namespace=service.namespace,
                label_selector=f"app={service.name}"
            )
            
            if len(pods.items) == 0:
                return {"status": "pending", "replicas": f"0/{desired_replicas}"}
            
            # Debug logging
            logger.debug(f"\n=== Checking status for {service.name} in namespace {service.namespace} ===")
            logger.debug(f"Found {len(pods.items)} pod(s)")
            
            # Collect status from all pods/containers before deciding
            has_crash_loop = False
            has_image_pull_error = False
            has_pending = False
            has_container_creating = False
            has_not_ready = False
            
            for pod in pods.items:
                pod_status = pod.status.phase
                logger.debug(f"\nPod: {pod.metadata.name}")
                logger.debug(f"  Phase: {pod_status}")
                
                # Failed pod phase
                if pod_status == "Failed":
                    logger.debug(f"  -> Pod phase is Failed")
                    has_crash_loop = True
                    continue
                
                # Check all container statuses
                if pod.status.container_statuses:
                    for container in pod.status.container_statuses:
                        logger.debug(f"  Container: {container.name}")
                        logger.debug(f"    Restart count: {container.restart_count}")
                        logger.debug(f"    Ready: {container.ready}")
                        
                        # High restart count = crash loop
                        if container.restart_count > 2:
                            logger.debug(f"    -> High restart count detected!")
                            has_crash_loop = True
                        
                        # Check waiting state (current)
                        if container.state.waiting:
                            reason = container.state.waiting.reason or ""
                            message = container.state.waiting.message or ""
                            logger.debug(f"    State: Waiting - Reason: {reason}")
                            logger.debug(f"    Message: {message}")
                            if "CrashLoopBackOff" in reason or "Error" in reason:
                                logger.debug(f"    -> Crash/Error detected in waiting state!")
                                has_crash_loop = True
                            elif "ImagePull" in reason:
                                logger.debug(f"    -> Image pull error detected!")
                                has_image_pull_error = True
                            elif reason in ["ContainerCreating", "PodInitializing"]:
                                has_container_creating = True
                        
                        # Check running state
                        if container.state.running:
                            logger.debug(f"    State: Running since {container.state.running.started_at}")
                            if not container.ready:
                                logger.debug(f"    -> Running but not ready!")
                                has_not_ready = True
                        
                        # Check terminated state (current)
                        if container.state.terminated:
                            reason = container.state.terminated.reason or ""
                            exit_code = container.state.terminated.exit_code
                            logger.debug(f"    State: Terminated - Reason: {reason}, Exit Code: {exit_code}")
                            if exit_code != 0:
                                logger.debug(f"    -> Non-zero exit code detected!")
                                has_crash_loop = True
                        
                        # Check last_state for recent crashes
                        # Only consider it a crash loop if container is NOT currently running healthy
                        if container.last_state and container.last_state.terminated:
                            reason = container.last_state.terminated.reason or ""
                            exit_code = container.last_state.terminated.exit_code
                            logger.debug(f"    Last State: Terminated - Reason: {reason}, Exit Code: {exit_code}")
                            # Only mark as crash if the container is not currently running AND healthy
                            if not (container.state.running and container.ready):
                                if reason in ["Error", "CrashLoopBackOff"]:
                                    logger.debug(f"    -> Crash detected in last state!")
                                    has_crash_loop = True
                                if exit_code != 0:
                                    logger.debug(f"    -> Non-zero exit code in last state!")
                                    has_crash_loop = True
                        
                        # If not ready for any reason
                        if not container.ready:
                            has_not_ready = True
                
                # Pending pod phase
                if pod_status == "Pending":
                    has_pending = True
            
            # Determine final status based on collected information
            logger.debug(f"\n=== Status Flags ===")
            logger.debug(f"  has_crash_loop: {has_crash_loop}")
            logger.debug(f"  has_image_pull_error: {has_image_pull_error}")
            logger.debug(f"  has_container_creating: {has_container_creating}")
            logger.debug(f"  has_pending: {has_pending}")
            logger.debug(f"  has_not_ready: {has_not_ready}")
            logger.debug(f"  available/desired replicas: {available_replicas}/{desired_replicas}")
            
            # Determine final status based on collected information
            if has_crash_loop:
                return {"status": "failed", "replicas": f"{available_replicas}/{desired_replicas}"}
            
            if has_image_pull_error:
                return {"status": "failed", "replicas": f"{available_replicas}/{desired_replicas}"}
            
            if has_container_creating:
                return {"status": "deploying", "replicas": f"{available_replicas}/{desired_replicas}"}
            
            if has_pending:
                return {"status": "pending", "replicas": f"{available_replicas}/{desired_replicas}"}
            
            if has_not_ready:
                return {"status": "degraded", "replicas": f"{available_replicas}/{desired_replicas}"}
            
            # All pods are running and ready
            if available_replicas == desired_replicas and desired_replicas > 0:
                return {"status": "running", "replicas": f"{available_replicas}/{desired_replicas}"}
            else:
                return {"status": "degraded", "replicas": f"{available_replicas}/{desired_replicas}"}
                
        except ApiException:
            # Fallback to deployment status only
            if available_replicas == desired_replicas and desired_replicas > 0:
                status = "running"
            else:
                status = "degraded"
            
            return {
                "status": status,
                "replicas": f"{available_replicas}/{desired_replicas}"
            }


async def _create_kafbat_secret(cluster: Cluster, client_secret: str):
    """Create Kubernetes secret for Kafbat UI Keycloak credentials."""
    from src.utils.kubernetes import kube_config_context
    
    with kube_config_context(cluster):
        core_v1 = client.CoreV1Api()
        
        secret_name = "keycloak-secrets"
        namespace = "streamlink"
        
        # Only store the client secret - client ID comes from ConfigMap
        secret_data = {
            "kafbat-client-secret": client_secret
        }
        
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=secret_name, namespace=namespace),
            string_data=secret_data,
            type="Opaque"
        )
        
        try:
            # Try to create the secret
            core_v1.create_namespaced_secret(namespace=namespace, body=secret)
            logger.info(f"Secret '{secret_name}' created in namespace '{namespace}'")
        except ApiException as e:
            if e.status == 409:
                # Secret already exists, update it
                core_v1.patch_namespaced_secret(name=secret_name, namespace=namespace, body=secret)
                logger.info(f"Secret '{secret_name}' updated in namespace '{namespace}'")
            else:
                raise


async def _delete_kafbat_secret(cluster: Cluster):
    """Delete Kubernetes secret for Kafbat UI Keycloak credentials."""
    from src.utils.kubernetes import kube_config_context
    
    with kube_config_context(cluster):
        core_v1 = client.CoreV1Api()
        
        secret_name = "keycloak-secrets"
        namespace = "streamlink"
        
        try:
            core_v1.delete_namespaced_secret(name=secret_name, namespace=namespace)
            logger.info(f"Secret '{secret_name}' deleted from namespace '{namespace}'")
        except ApiException as e:
            if e.status == 404:
                logger.debug(f"Secret '{secret_name}' not found (already deleted)")
            else:
                raise


async def _ensure_global_config(cluster, namespace: str = "streamlink"):
    """Create/update global ConfigMap automatically from settings object.
    
    Reads all non-secret fields from settings and creates a Kubernetes ConfigMap.
    Secret fields (marked with json_schema_extra={'secret': True}) are excluded.
    """
    from src.utils.kubernetes import kube_config_context
    
    logger.info(f"Creating global ConfigMap for namespace: {namespace}")
    
    with kube_config_context(cluster):
        
        # Ensure namespace exists first
        core_v1 = client.CoreV1Api()
        try:
            core_v1.read_namespace(namespace)
        except ApiException as e:
            if e.status == 404:
                # Create namespace if it doesn't exist
                namespace_manifest = client.V1Namespace(
                    metadata=client.V1ObjectMeta(name=namespace)
                )
                core_v1.create_namespace(namespace_manifest)
                logger.info(f"✓ Created namespace '{namespace}'")
            else:
                raise
        
        # Auto-generate config data from settings object
        config_data = {}
        
        logger.debug(f"Processing {len(settings.model_fields)} fields from settings")
        
        # Iterate through all Pydantic fields
        for field_name, field_info in settings.model_fields.items():
            # Skip fields marked as secret
            if field_info.json_schema_extra and field_info.json_schema_extra.get('secret'):
                continue
            
            # Get the value from settings
            value = getattr(settings, field_name)
            
            # Skip None values
            if value is None:
                continue
            
            # Convert field name to kebab-case for Kubernetes
            k8s_key = field_name.lower().replace('_', '-')
            
            # Convert value to string (ConfigMaps only store strings)
            if isinstance(value, bool):
                config_data[k8s_key] = "true" if value else "false"
            elif isinstance(value, (list, dict)):
                import json
                config_data[k8s_key] = json.dumps(value)
            else:
                config_data[k8s_key] = str(value)
        
        logger.debug(f"Total config values to store: {len(config_data)}")
        logger.debug(f"Sample keys: {list(config_data.keys())[:5]}")
        
        # Create ConfigMap manifest
        config_map = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": "streamlink-config",
                "namespace": namespace
            },
            "data": config_data
        }
        
        # Apply to Kubernetes
        core_v1 = client.CoreV1Api()
        try:
            logger.info(f"Attempting to create ConfigMap in namespace '{namespace}'")
            core_v1.create_namespaced_config_map(namespace, config_map)
            logger.info(f"✅ Created ConfigMap 'streamlink-config' with {len(config_data)} config values")
        except ApiException as e:
            if e.status == 409:  # Already exists, update it
                logger.info("ConfigMap exists, updating...")
                core_v1.replace_namespaced_config_map("streamlink-config", namespace, config_map)
                logger.info(f"✅ Updated ConfigMap 'streamlink-config' with {len(config_data)} config values")
            else:
                logger.error(f"❌ Failed to create/update ConfigMap: {e.status} - {e.reason}")
                raise


async def _ensure_dependency_config(cluster: Cluster, db: AsyncSession, namespace: str = "streamlink"):
    """Publish dependency information (internal hosts/ports) and ensure required secrets.

    Currently supports Postgres. Creates/updates ConfigMap 'streamlink-deps' with:
    - postgres-host, postgres-port
    - keycloak-db-username (for consumers)
    - keycloak-db-url (computed JDBC URL for Keycloak)

    Also ensures 'postgres-secret' exists, creating from DB if missing.
    """
    from src.utils.kubernetes import kube_config_context

    with kube_config_context(cluster):
        core_v1 = client.CoreV1Api()

        # Ensure namespace exists
        try:
            core_v1.read_namespace(namespace)
        except ApiException as e:
            if e.status == 404:
                ns = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace))
                core_v1.create_namespace(ns)
                logger.info(f"✓ Created namespace '{namespace}' for dependency config")
            else:
                raise

        # Ensure postgres-secret exists. If missing, recreate from Service record.
        need_pg_secret = False
        try:
            core_v1.read_namespaced_secret("postgres-secret", namespace)
        except ApiException as e:
            if e.status == 404:
                need_pg_secret = True
            else:
                raise

        if need_pg_secret:
            logger.info("postgres-secret not found. Attempting to recreate from DB service record...")
            stmt = select(Service).where(Service.cluster_id == cluster.id, Service.manifest_name == "postgres", Service.is_active == True)
            res = await db.execute(stmt)
            pg_service = res.scalar_one_or_none()
            if pg_service and pg_service.password:
                crypto = get_crypto_service()
                try:
                    pg_pwd = crypto.decrypt(pg_service.password)
                except Exception:
                    pg_pwd = ""
                if pg_pwd:
                    secret = client.V1Secret(
                        metadata=client.V1ObjectMeta(name="postgres-secret", namespace=namespace),
                        string_data={"postgres-password": pg_pwd}
                    )
                    try:
                        core_v1.create_namespaced_secret(namespace, secret)
                        logger.info("✓ Recreated 'postgres-secret' from DB")
                    except ApiException as e:
                        if e.status == 409:
                            core_v1.patch_namespaced_secret("postgres-secret", namespace, secret)
                            logger.info("✓ Updated 'postgres-secret' from DB")
                        else:
                            raise
            else:
                logger.warning("Cannot recreate 'postgres-secret': missing service record or password")

        # Publish internal host/port via ConfigMap
        postgres_host = "postgres.streamlink.svc.cluster.local"
        postgres_port = "5432"
        stmt = select(Service).where(Service.cluster_id == cluster.id, Service.manifest_name == "postgres", Service.is_active == True)
        res = await db.execute(stmt)
        pg_service = res.scalar_one_or_none()
        if pg_service:
            postgres_host = pg_service.internal_host or postgres_host
            postgres_port = pg_service.internal_port or postgres_port

        deps_map = client.V1ConfigMap(
            metadata=client.V1ObjectMeta(name="streamlink-deps", namespace=namespace),
            data={
                "postgres-host": postgres_host,
                "postgres-port": postgres_port,
                "keycloak-db-username": "keycloak",
                "keycloak-db-url": f"jdbc:postgresql://{postgres_host}:{postgres_port}/keycloak"
            }
        )
        try:
            core_v1.create_namespaced_config_map(namespace, deps_map)
            logger.info("✓ Created ConfigMap 'streamlink-deps'")
        except ApiException as e:
            if e.status == 409:
                core_v1.replace_namespaced_config_map("streamlink-deps", namespace, deps_map)
                logger.info("✓ Updated ConfigMap 'streamlink-deps'")
            else:
                raise
