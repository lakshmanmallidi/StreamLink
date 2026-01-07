"""Cluster management endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import base64
import tempfile
import os

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from src.database import get_db
from src.models.cluster import Cluster
from src.utils.crypto import get_crypto_service

router = APIRouter(prefix="/v1/clusters", tags=["Clusters"])


class ClusterCreate(BaseModel):
    name: str
    api_server: str
    kubeconfig: str


class ClusterUpdate(BaseModel):
    name: Optional[str] = None
    api_server: Optional[str] = None
    kubeconfig: Optional[str] = None


class ClusterResponse(BaseModel):
    id: str
    name: str
    api_server: str
    status: str
    last_checked: Optional[datetime]
    is_active: bool
    created_at: datetime


@router.get("", response_model=List[ClusterResponse])
async def list_clusters(db: AsyncSession = Depends(get_db)):
    """List all clusters."""
    stmt = select(Cluster).where(Cluster.is_active == True)
    result = await db.execute(stmt)
    clusters = result.scalars().all()
    
    return [
        ClusterResponse(
            id=str(cluster.id),
            name=cluster.name,
            api_server=cluster.api_server,
            status=cluster.status,
            last_checked=cluster.last_checked,
            is_active=cluster.is_active,
            created_at=cluster.created_at
        )
        for cluster in clusters
    ]


@router.post("", response_model=ClusterResponse)
async def create_cluster(data: ClusterCreate, db: AsyncSession = Depends(get_db)):
    """Add a new Kubernetes cluster. Only one cluster is allowed."""
    # Check if any active cluster exists
    stmt = select(Cluster).where(Cluster.is_active == True)
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(status_code=400, detail="Only one cluster is allowed. Please delete the existing cluster first.")
    
    # Encrypt kubeconfig before storing
    crypto = get_crypto_service()
    encrypted_kubeconfig = crypto.encrypt(data.kubeconfig)
    
    cluster = Cluster(
        name=data.name,
        api_server=data.api_server,
        kubeconfig=encrypted_kubeconfig,
        status="unknown"
    )
    
    db.add(cluster)
    await db.commit()
    await db.refresh(cluster)
    
    return ClusterResponse(
        id=str(cluster.id),
        name=cluster.name,
        api_server=cluster.api_server,
        status=cluster.status,
        last_checked=cluster.last_checked,
        is_active=cluster.is_active,
        created_at=cluster.created_at
    )


@router.get("/{cluster_id}", response_model=ClusterResponse)
async def get_cluster(cluster_id: str, db: AsyncSession = Depends(get_db)):
    """Get cluster by ID."""
    stmt = select(Cluster).where(Cluster.id == cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    return ClusterResponse(
        id=str(cluster.id),
        name=cluster.name,
        api_server=cluster.api_server,
        status=cluster.status,
        last_checked=cluster.last_checked,
        is_active=cluster.is_active,
        created_at=cluster.created_at
    )


@router.put("/{cluster_id}", response_model=ClusterResponse)
async def update_cluster(
    cluster_id: str,
    data: ClusterUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update cluster connection details."""
    stmt = select(Cluster).where(Cluster.id == cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    crypto = get_crypto_service()
    
    if data.name:
        cluster.name = data.name
    if data.api_server:
        cluster.api_server = data.api_server
    if data.kubeconfig:
        # Encrypt kubeconfig before updating
        cluster.kubeconfig = crypto.encrypt(data.kubeconfig)
    
    cluster.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(cluster)
    
    return ClusterResponse(
        id=str(cluster.id),
        name=cluster.name,
        api_server=cluster.api_server,
        status=cluster.status,
        last_checked=cluster.last_checked,
        is_active=cluster.is_active,
        created_at=cluster.created_at
    )


@router.delete("/{cluster_id}")
async def delete_cluster(cluster_id: str, db: AsyncSession = Depends(get_db)):
    """Delete cluster."""
    stmt = select(Cluster).where(Cluster.id == cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    cluster.is_active = False
    await db.commit()
    
    return {"message": "Cluster deleted successfully"}


@router.post("/{cluster_id}/check-status")
async def check_cluster_status(cluster_id: str, db: AsyncSession = Depends(get_db)):
    """Check if cluster is up or down by connecting to Kubernetes API."""
    stmt = select(Cluster).where(Cluster.id == cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Decrypt kubeconfig and check cluster health
    crypto = get_crypto_service()
    try:
        decrypted_kubeconfig = crypto.decrypt(cluster.kubeconfig)
        
        # Write kubeconfig to temporary file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as temp_file:
            temp_file.write(decrypted_kubeconfig)
            temp_kubeconfig_path = temp_file.name
        
        try:
            # Load kubeconfig and create API client
            config.load_kube_config(config_file=temp_kubeconfig_path)
            v1 = client.CoreV1Api()
            
            # Try to get cluster version - simple health check
            version = client.VersionApi().get_code()
            
            # If we get here, cluster is up
            cluster.status = "up"
            cluster.last_checked = datetime.utcnow()
        except ApiException as e:
            # Kubernetes API error - cluster is down or unreachable
            cluster.status = "down"
            cluster.last_checked = datetime.utcnow()
        except Exception as e:
            # Any other error - cluster is down
            cluster.status = "down"
            cluster.last_checked = datetime.utcnow()
        finally:
            # Clean up temporary file
            if os.path.exists(temp_kubeconfig_path):
                os.unlink(temp_kubeconfig_path)
    except Exception as e:
        # Failed to decrypt or process kubeconfig
        cluster.status = "unknown"
        cluster.last_checked = datetime.utcnow()
        raise HTTPException(status_code=500, detail=f"Failed to check cluster status: {str(e)}")
    
    await db.commit()
    
    return {"status": cluster.status, "last_checked": cluster.last_checked}
