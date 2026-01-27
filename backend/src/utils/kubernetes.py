"""Kubernetes utility functions."""
import tempfile
import os
from contextlib import contextmanager
from typing import Generator, Optional

from kubernetes import config, client
from src.models.cluster import Cluster
from src.utils.crypto import get_crypto_service


@contextmanager
def kube_config_context(cluster: Cluster) -> Generator[str, None, None]:
    """Context manager for loading kubeconfig from encrypted cluster data.
    
    Usage:
        with kube_config_context(cluster) as temp_path:
            # Kubeconfig is loaded, use kubernetes client APIs
            core_v1 = client.CoreV1Api()
            pods = core_v1.list_namespaced_pod(...)
    
    Args:
        cluster: Cluster object with encrypted kubeconfig
        
    Yields:
        str: Path to temporary kubeconfig file (for reference, already loaded)
    """
    crypto = get_crypto_service()
    decrypted_kubeconfig = crypto.decrypt(cluster.kubeconfig)
    
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.yaml') as temp_file:
        temp_file.write(decrypted_kubeconfig)
        temp_kubeconfig_path = temp_file.name
    
    try:
        config.load_kube_config(config_file=temp_kubeconfig_path)
        yield temp_kubeconfig_path
    finally:
        if os.path.exists(temp_kubeconfig_path):
            os.unlink(temp_kubeconfig_path)


def get_node_ip(cluster: Cluster) -> Optional[str]:
    """Get Kubernetes node IP for external access.
    
    Args:
        cluster: Cluster object
        
    Returns:
        Node IP address (ExternalIP preferred, InternalIP as fallback) or None
    """
    try:
        with kube_config_context(cluster):
            core_v1 = client.CoreV1Api()
            nodes = core_v1.list_node()
            
            if not nodes.items:
                return None
            
            # Get first node's external or internal IP
            for address in nodes.items[0].status.addresses:
                if address.type == "ExternalIP":
                    return address.address
            
            # Fallback to internal IP
            for address in nodes.items[0].status.addresses:
                if address.type == "InternalIP":
                    return address.address
                    
    except Exception:
        return None
    
    return None
