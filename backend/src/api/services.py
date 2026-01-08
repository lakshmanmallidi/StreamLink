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
from src.utils.dependencies import dependency_resolver, SERVICE_DISPLAY_NAMES

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
    
    # Get missing dependencies
    missing_deps = dependency_resolver.get_missing_dependencies(data.name, installed_manifest_names)
    
    # Install missing dependencies first (in order)
    for dep_name in missing_deps:
        print(f"Installing dependency: {dep_name}")
        try:
            deployed_name, deployed_namespace = await _deploy_to_kubernetes(cluster, dep_name)
            
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
            
            print(f"Successfully deployed dependency: {deployed_name} in namespace {deployed_namespace}")
            installed_manifest_names.add(dep_name)
            
        except Exception as e:
            error_msg = f"Failed to deploy dependency '{dep_name}': {str(e)}"
            print(f"ERROR: {error_msg}")
            raise HTTPException(status_code=500, detail=error_msg)
    
    # Now deploy the target service
    try:
        print(f"Deploying target service: {data.name}")
        deployed_name, deployed_namespace = await _deploy_to_kubernetes(cluster, data.name)
        print(f"Successfully deployed {deployed_name} to Kubernetes in namespace {deployed_namespace}")
    except Exception as e:
        error_msg = f"Failed to deploy {data.name} to Kubernetes: {str(e)}"
        print(f"ERROR: {error_msg}")
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
    
    print(f"Service {service.name} and all dependencies deployed successfully.")
    
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
    
    # Delete dependent services first (in reverse dependency order)
    if cascade and dependent_services:
        print(f"Cascading delete: will delete {len(dependent_services)} dependent service(s)")
        for dep_svc in dependent_services:
            if cluster:
                try:
                    print(f"Deleting dependent service '{dep_svc.name}' from namespace '{dep_svc.namespace}'")
                    await _delete_from_kubernetes(cluster, dep_svc)
                    print(f"Successfully deleted dependent service '{dep_svc.name}'")
                except Exception as e:
                    print(f"ERROR: Failed to delete dependent service: {type(e).__name__}: {e}")
            
            dep_svc.is_active = False
            dep_svc.status = "deleted"
            deleted_services.append(dep_svc.display_name)
    
    # Delete the target service
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
    deleted_services.append(service.display_name)
    await db.commit()
    
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


async def _deploy_to_kubernetes(cluster: Cluster, service_name: str) -> tuple[str, str]:
    """Deploy service to Kubernetes cluster using YAML manifest.
    Returns (deployed_name, deployed_namespace) tuple.
    """
    crypto = get_crypto_service()
    decrypted_kubeconfig = crypto.decrypt(cluster.kubeconfig)
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as temp_file:
        temp_file.write(decrypted_kubeconfig)
        temp_kubeconfig_path = temp_file.name
    
    deployed_namespace = None
    deployed_name = None
    
    try:
        config.load_kube_config(config_file=temp_kubeconfig_path)
        
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
            
            # Apply based on resource type
            if kind == "Namespace":
                core_v1 = client.CoreV1Api()
                try:
                    core_v1.create_namespace(body=doc)
                except ApiException as e:
                    if e.status != 409:  # Ignore if already exists
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
    finally:
        if os.path.exists(temp_kubeconfig_path):
            os.unlink(temp_kubeconfig_path)
    
    return deployed_name or service_name, deployed_namespace or "default"


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
        
        print(f"Deleting deployment/statefulset '{service.name}' from namespace '{service.namespace}'")
        # Try to delete deployment first
        try:
            apps_v1.delete_namespaced_deployment(
                name=service.name,
                namespace=service.namespace,
                propagation_policy='Foreground'
            )
            print(f"Deployment '{service.name}' deletion initiated")
        except ApiException as e:
            if e.status == 404:
                # Not a deployment, try statefulset
                try:
                    apps_v1.delete_namespaced_stateful_set(
                        name=service.name,
                        namespace=service.namespace,
                        propagation_policy='Foreground'
                    )
                    print(f"StatefulSet '{service.name}' deletion initiated")
                except ApiException as e2:
                    if e2.status == 404:
                        print(f"Deployment/StatefulSet '{service.name}' not found (already deleted)")
                    else:
                        raise
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
                        # Only consider it a crash loop if container is NOT currently running healthy
                        if container.last_state and container.last_state.terminated:
                            reason = container.last_state.terminated.reason or ""
                            exit_code = container.last_state.terminated.exit_code
                            print(f"    Last State: Terminated - Reason: {reason}, Exit Code: {exit_code}")
                            # Only mark as crash if the container is not currently running AND healthy
                            if not (container.state.running and container.ready):
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
