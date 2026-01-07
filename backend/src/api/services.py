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

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from src.database import get_db
from src.models.service import Service
from src.models.cluster import Cluster
from src.utils.crypto import get_crypto_service

router = APIRouter(prefix="/v1/services", tags=["Services"])


class ServiceDeploy(BaseModel):
    cluster_id: str
    name: str
    namespace: Optional[str] = "default"
    config: Optional[dict] = None


class ServiceResponse(BaseModel):
    id: str
    cluster_id: str
    name: str
    display_name: str
    namespace: str
    status: str
    version: Optional[str]
    replicas: Optional[str]
    last_checked: Optional[datetime]
    is_active: bool
    created_at: datetime


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


@router.post("", response_model=ServiceResponse)
async def deploy_service(data: ServiceDeploy, db: AsyncSession = Depends(get_db)):
    """Deploy a service to Kubernetes cluster."""
    # Get cluster
    stmt = select(Cluster).where(Cluster.id == data.cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    if not cluster:
        raise HTTPException(status_code=404, detail="Cluster not found")
    
    # Check if service already deployed
    stmt = select(Service).where(
        Service.cluster_id == data.cluster_id,
        Service.name == data.name,
        Service.is_active == True
    )
    result = await db.execute(stmt)
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(status_code=400, detail=f"Service '{data.name}' is already deployed")
    
    # Create service record
    display_names = {
        "schema-registry": "Schema Registry",
        "kafka": "Apache Kafka"
    }
    
    service = Service(
        cluster_id=data.cluster_id,
        name=data.name,
        display_name=display_names.get(data.name, data.name.title()),
        namespace=data.namespace,
        status="deploying"
    )
    
    db.add(service)
    await db.commit()
    await db.refresh(service)
    
    # Deploy to Kubernetes
    try:
        await _deploy_to_kubernetes(cluster, service, data.namespace)
        # Keep status as "deploying" - let the status check endpoint update it to "running" when pods are ready
        print(f"Kubernetes manifests applied for {service.name}. Status will be updated by periodic checks.")
    except Exception as e:
        service.status = "failed"
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Deployment failed: {str(e)}")
    
    await db.commit()
    
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


@router.delete("/{service_id}")
async def delete_service(service_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a service from Kubernetes cluster."""
    stmt = select(Service).where(Service.id == service_id)
    result = await db.execute(stmt)
    service = result.scalar_one_or_none()
    
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    
    # Get cluster
    stmt = select(Cluster).where(Cluster.id == service.cluster_id)
    result = await db.execute(stmt)
    cluster = result.scalar_one_or_none()
    
    if cluster:
        try:
            print(f"Attempting to delete service '{service.name}' from namespace '{service.namespace}'")
            await _delete_from_kubernetes(cluster, service)
            print(f"Successfully deleted service '{service.name}' from Kubernetes")
        except Exception as e:
            print(f"ERROR: Failed to delete from Kubernetes: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
    else:
        print(f"Warning: No cluster found for service {service.id}, skipping Kubernetes deletion")
    
    service.is_active = False
    service.status = "deleted"
    await db.commit()
    
    return {"message": "Service deleted successfully"}


@router.post("/{service_id}/check-status")
async def check_service_status(service_id: str, db: AsyncSession = Depends(get_db)):
    """Check service status in Kubernetes."""
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


async def _deploy_to_kubernetes(cluster: Cluster, service: Service, namespace: str):
    """Deploy service to Kubernetes cluster using YAML manifest."""
    crypto = get_crypto_service()
    decrypted_kubeconfig = crypto.decrypt(cluster.kubeconfig)
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as temp_file:
        temp_file.write(decrypted_kubeconfig)
        temp_kubeconfig_path = temp_file.name
    
    try:
        config.load_kube_config(config_file=temp_kubeconfig_path)
        
        # Load YAML manifest for the service
        manifest_path = os.path.join(
            os.path.dirname(__file__), 
            '..', '..', 
            'deployments', 
            f'{service.name}.yaml'
        )
        
        if not os.path.exists(manifest_path):
            raise ValueError(f"Deployment manifest not found: {manifest_path}")
        
        # Read and apply the YAML manifest
        with open(manifest_path, 'r') as f:
            manifest_content = f.read()
        
        # Replace namespace if different from default
        if namespace != "streamlink":
            manifest_content = manifest_content.replace("namespace: streamlink", f"namespace: {namespace}")
        
        # Apply the manifest using kubectl-like approach
        from kubernetes import utils
        k8s_client = client.ApiClient()
        
        # Parse and apply each document in the YAML
        for doc in yaml.safe_load_all(manifest_content):
            if doc is None:
                continue
            
            kind = doc.get('kind')
            api_version = doc.get('apiVersion')
            
            # Update namespace if specified
            if namespace != "streamlink" and 'metadata' in doc:
                doc['metadata']['namespace'] = namespace
            
            # Apply based on resource type
            if kind == "Namespace":
                core_v1 = client.CoreV1Api()
                try:
                    core_v1.create_namespace(body=doc)
                except ApiException as e:
                    if e.status != 409:  # Ignore if already exists
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
    finally:
        if os.path.exists(temp_kubeconfig_path):
            os.unlink(temp_kubeconfig_path)


async def _delete_from_kubernetes(cluster: Cluster, service: Service):
    """Delete service from Kubernetes cluster."""
    crypto = get_crypto_service()
    decrypted_kubeconfig = crypto.decrypt(cluster.kubeconfig)
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as temp_file:
        temp_file.write(decrypted_kubeconfig)
        temp_kubeconfig_path = temp_file.name
    
    try:
        config.load_kube_config(config_file=temp_kubeconfig_path)
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        print(f"Deleting deployment '{service.name}' from namespace '{service.namespace}'")
        # Delete deployment
        try:
            apps_v1.delete_namespaced_deployment(
                name=service.name,
                namespace=service.namespace,
                propagation_policy='Foreground'
            )
            print(f"Deployment '{service.name}' deletion initiated")
        except ApiException as e:
            if e.status == 404:
                print(f"Deployment '{service.name}' not found (already deleted)")
            else:
                raise
        
        print(f"Deleting service '{service.name}' from namespace '{service.namespace}'")
        # Delete service
        try:
            core_v1.delete_namespaced_service(
                name=service.name,
                namespace=service.namespace
            )
            print(f"Service '{service.name}' deletion initiated")
        except ApiException as e:
            if e.status == 404:
                print(f"Service '{service.name}' not found (already deleted)")
            else:
                raise
    finally:
        if os.path.exists(temp_kubeconfig_path):
            os.unlink(temp_kubeconfig_path)


async def _check_kubernetes_status(cluster: Cluster, service: Service):
    """Check service status in Kubernetes by examining pod health."""
    crypto = get_crypto_service()
    decrypted_kubeconfig = crypto.decrypt(cluster.kubeconfig)
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as temp_file:
        temp_file.write(decrypted_kubeconfig)
        temp_kubeconfig_path = temp_file.name
    
    try:
        config.load_kube_config(config_file=temp_kubeconfig_path)
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        # Get deployment status
        try:
            deployment = apps_v1.read_namespaced_deployment(
                name=service.name,
                namespace=service.namespace
            )
        except ApiException as e:
            if e.status == 404:
                return {"status": "not_found", "replicas": "0/0"}
            raise
        
        desired_replicas = deployment.spec.replicas or 0
        available_replicas = deployment.status.available_replicas or 0
        
        # Get pod status for more detailed information
        try:
            pods = core_v1.list_namespaced_pod(
                namespace=service.namespace,
                label_selector=f"app={service.name}"
            )
            
            if len(pods.items) == 0:
                return {"status": "pending", "replicas": f"0/{desired_replicas}"}
            
            # Debug logging
            print(f"\n=== Checking status for {service.name} in namespace {service.namespace} ===")
            print(f"Found {len(pods.items)} pod(s)")
            
            # Collect status from all pods/containers before deciding
            has_crash_loop = False
            has_image_pull_error = False
            has_pending = False
            has_container_creating = False
            has_not_ready = False
            
            for pod in pods.items:
                pod_status = pod.status.phase
                print(f"\nPod: {pod.metadata.name}")
                print(f"  Phase: {pod_status}")
                
                # Failed pod phase
                if pod_status == "Failed":
                    print(f"  -> Pod phase is Failed")
                    has_crash_loop = True
                    continue
                
                # Check all container statuses
                if pod.status.container_statuses:
                    for container in pod.status.container_statuses:
                        print(f"  Container: {container.name}")
                        print(f"    Restart count: {container.restart_count}")
                        print(f"    Ready: {container.ready}")
                        
                        # High restart count = crash loop
                        if container.restart_count > 2:
                            print(f"    -> High restart count detected!")
                            has_crash_loop = True
                        
                        # Check waiting state (current)
                        if container.state.waiting:
                            reason = container.state.waiting.reason or ""
                            message = container.state.waiting.message or ""
                            print(f"    State: Waiting - Reason: {reason}")
                            print(f"    Message: {message}")
                            if "CrashLoopBackOff" in reason or "Error" in reason:
                                print(f"    -> Crash/Error detected in waiting state!")
                                has_crash_loop = True
                            elif "ImagePull" in reason:
                                print(f"    -> Image pull error detected!")
                                has_image_pull_error = True
                            elif reason in ["ContainerCreating", "PodInitializing"]:
                                has_container_creating = True
                        
                        # Check running state
                        if container.state.running:
                            print(f"    State: Running since {container.state.running.started_at}")
                            if not container.ready:
                                print(f"    -> Running but not ready!")
                                has_not_ready = True
                        
                        # Check terminated state (current)
                        if container.state.terminated:
                            reason = container.state.terminated.reason or ""
                            exit_code = container.state.terminated.exit_code
                            print(f"    State: Terminated - Reason: {reason}, Exit Code: {exit_code}")
                            if exit_code != 0:
                                print(f"    -> Non-zero exit code detected!")
                                has_crash_loop = True
                        
                        # Check last_state for recent crashes
                        if container.last_state and container.last_state.terminated:
                            reason = container.last_state.terminated.reason or ""
                            exit_code = container.last_state.terminated.exit_code
                            print(f"    Last State: Terminated - Reason: {reason}, Exit Code: {exit_code}")
                            if reason in ["Error", "CrashLoopBackOff"]:
                                print(f"    -> Crash detected in last state!")
                                has_crash_loop = True
                            if exit_code != 0:
                                print(f"    -> Non-zero exit code in last state!")
                                has_crash_loop = True
                        
                        # If not ready for any reason
                        if not container.ready:
                            has_not_ready = True
                
                # Pending pod phase
                if pod_status == "Pending":
                    has_pending = True
            
            # Determine final status based on collected information
            print(f"\n=== Status Flags ===")
            print(f"  has_crash_loop: {has_crash_loop}")
            print(f"  has_image_pull_error: {has_image_pull_error}")
            print(f"  has_container_creating: {has_container_creating}")
            print(f"  has_pending: {has_pending}")
            print(f"  has_not_ready: {has_not_ready}")
            print(f"  available/desired replicas: {available_replicas}/{desired_replicas}")
            print()
            
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
    finally:
        if os.path.exists(temp_kubeconfig_path):
            os.unlink(temp_kubeconfig_path)
