"""Service dependency configuration and resolution."""
from typing import List, Dict, Set, Optional
from collections import defaultdict, deque


# Service dependency graph
# Key: service name, Value: list of dependencies
SERVICE_DEPENDENCIES: Dict[str, List[str]] = {
    "postgres": [],  # No dependencies
    "keycloak": ["postgres"],  # Depends on Postgres
    "kafka": [],  # No dependencies
    "schema-registry": ["kafka"],  # Depends on Kafka
    "kafka-connect": ["kafka", "schema-registry"],  # Depends on both
    "ksqldb": ["kafka", "schema-registry", "kafka-connect"],  # Depends on Kafka, Schema Registry, and Kafka Connect
    "kafka-rest": ["kafka", "schema-registry"],  # Depends on both
    "kafbat-ui": ["kafka", "schema-registry", "kafka-connect", "ksqldb", "keycloak"],  # UI depends on all services
}


# Service display names
SERVICE_DISPLAY_NAMES: Dict[str, str] = {
    "postgres": "PostgreSQL Database",
    "keycloak": "Keycloak (Authentication)",
    "kafka": "Apache Kafka",
    "schema-registry": "Schema Registry",
    "kafka-connect": "Kafka Connect",
    "ksqldb": "ksqlDB",
    "kafka-rest": "Kafka REST Proxy",
    "kafbat-ui": "Kafbat UI",
}


class DependencyResolver:
    """Resolves service dependencies and determines installation order."""
    
    def __init__(self, dependencies: Dict[str, List[str]] = None):
        """Initialize with dependency graph."""
        self.dependencies = dependencies or SERVICE_DEPENDENCIES
    
    def get_dependencies(self, service_name: str) -> List[str]:
        """Get direct dependencies for a service."""
        return self.dependencies.get(service_name, [])
    
    def get_all_dependencies(self, service_name: str) -> List[str]:
        """Get all dependencies (transitive) for a service in installation order."""
        if service_name not in self.dependencies:
            return []
        
        visited = set()
        order = []
        
        def visit(svc: str):
            if svc in visited:
                return
            visited.add(svc)
            
            # Visit dependencies first
            for dep in self.dependencies.get(svc, []):
                visit(dep)
            
            # Add current service after its dependencies
            order.append(svc)
        
        visit(service_name)
        
        # Remove the target service itself from the list
        if service_name in order:
            order.remove(service_name)
        
        return order
    
    def resolve_installation_order(self, services: List[str]) -> List[str]:
        """
        Resolve installation order for multiple services.
        Returns list of services in the order they should be installed.
        Uses topological sort to handle dependencies.
        """
        # Build in-degree map (count of dependencies)
        in_degree = defaultdict(int)
        adj_list = defaultdict(list)
        
        all_services = set(services)
        
        # Include all transitive dependencies
        for service in services:
            all_services.add(service)
            for dep in self.get_all_dependencies(service):
                all_services.add(dep)
        
        # Build graph
        for service in all_services:
            for dep in self.dependencies.get(service, []):
                adj_list[dep].append(service)
                in_degree[service] += 1
            # Ensure service is in in_degree map
            if service not in in_degree:
                in_degree[service] = 0
        
        # Topological sort using Kahn's algorithm
        queue = deque([svc for svc in all_services if in_degree[svc] == 0])
        result = []
        
        while queue:
            current = queue.popleft()
            result.append(current)
            
            for neighbor in adj_list[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        # Check for cycles
        if len(result) != len(all_services):
            raise ValueError("Circular dependency detected in service graph")
        
        return result
    
    def check_circular_dependencies(self) -> Optional[List[str]]:
        """
        Check if there are circular dependencies.
        Returns the cycle path if found, None otherwise.
        """
        visited = set()
        rec_stack = set()
        
        def has_cycle(service: str, path: List[str]) -> Optional[List[str]]:
            visited.add(service)
            rec_stack.add(service)
            path.append(service)
            
            for dep in self.dependencies.get(service, []):
                if dep not in visited:
                    cycle = has_cycle(dep, path[:])
                    if cycle:
                        return cycle
                elif dep in rec_stack:
                    # Found cycle
                    cycle_start = path.index(dep)
                    return path[cycle_start:] + [dep]
            
            rec_stack.remove(service)
            return None
        
        for service in self.dependencies:
            if service not in visited:
                cycle = has_cycle(service, [])
                if cycle:
                    return cycle
        
        return None
    
    def get_missing_dependencies(
        self, 
        service_name: str, 
        installed_services: Set[str]
    ) -> List[str]:
        """
        Get list of dependencies that are not yet installed.
        Returns them in the order they should be installed.
        """
        all_deps = self.get_all_dependencies(service_name)
        missing = [dep for dep in all_deps if dep not in installed_services]
        return missing


# Singleton instance
dependency_resolver = DependencyResolver()
