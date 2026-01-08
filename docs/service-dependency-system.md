# Service Dependency Management System

## Overview

Implemented a comprehensive service dependency management system that automatically resolves and installs prerequisite services in the correct order.

## Key Features

### 1. **Dependency Graph Configuration**
- Centralized dependency definitions in `backend/src/utils/dependencies.py`
- Current dependency mappings:
  ```
  kafka             → No dependencies
  schema-registry   → kafka
  kafka-connect     → kafka, schema-registry
  ksqldb            → kafka
  kafka-rest        → kafka, schema-registry
  ```

### 2. **Dependency Resolution Algorithm**
- **Topological Sort**: Determines correct installation order using Kahn's algorithm
- **Circular Dependency Detection**: Prevents invalid dependency graphs
- **Transitive Dependencies**: Automatically resolves all nested dependencies
- **Missing Dependency Detection**: Identifies which services need to be installed

### 3. **Backend API Enhancements**

#### New Endpoint: `POST /v1/services/deployment-plan`
Returns a deployment plan showing:
- Target service
- All dependencies (installed vs will_install)
- Total number of services to install
- Human-readable message

**Example Response:**
```json
{
  "target_service": "schema-registry",
  "target_display_name": "Schema Registry",
  "dependencies": [
    {
      "name": "kafka",
      "display_name": "Apache Kafka",
      "status": "will_install",
      "order": 0
    }
  ],
  "total_to_install": 1,
  "message": "Will install 1 dependency service(s) before Schema Registry."
}
```

#### Modified Endpoint: `POST /v1/services`
Now automatically:
1. Checks for missing dependencies
2. Installs dependencies in correct order
3. Creates DB records for each service
4. Deploys target service last

### 4. **Frontend UI Enhancements**

#### Deployment Plan Modal
- Shows all dependencies with status badges
- Displays installation order (numbered)
- Color-coded: Green (installed), Yellow (will install)
- Clear "Deploy All" button with count
- Cancel option

#### Service Cards
- Updated descriptions to mention dependencies
- Disabled state for coming soon services
- Visual feedback during deployment

### 5. **Database Schema**

#### New Model: `ServiceDependency`
```python
class ServiceDependency(Base):
    id: UUID
    service_name: str (indexed)
    depends_on: str (indexed)
    order: int
```

Note: Currently using code-based dependency graph. Database table available for future runtime configuration.

## Usage Flow

### User Perspective

1. **User clicks "Deploy" on Schema Registry** (which depends on Kafka)

2. **System shows deployment plan**:
   ```
   Dependencies:
   1. Apache Kafka [Will Install]
   
   → Schema Registry (Target)
   
   Message: Will install 1 dependency service(s) before Schema Registry.
   ```

3. **User clicks "Deploy All (2 services)"**

4. **System executes**:
   - Deploy Kafka to Kubernetes ✓
   - Create Kafka DB record ✓
   - Deploy Schema Registry to Kubernetes ✓
   - Create Schema Registry DB record ✓

5. **Success message**: "schema-registry and all dependencies deployed successfully!"

### Developer Perspective

**Adding a new service with dependencies:**

1. Create YAML manifest: `backend/deployments/my-service.yaml`

2. Update dependency graph:
   ```python
   # backend/src/utils/dependencies.py
   SERVICE_DEPENDENCIES = {
       ...
       "my-service": ["kafka", "schema-registry"],
   }
   
   SERVICE_DISPLAY_NAMES = {
       ...
       "my-service": "My Service",
   }
   ```

3. Update frontend:
   ```javascript
   // frontend/src/pages/Services.jsx
   const availableServices = [
     ...
     {
       name: "my-service",
       displayName: "My Service",
       description: "Description. Requires Kafka and Schema Registry.",
       icon: "🎯",
       dependencies: ["kafka", "schema-registry"],
     },
   ];
   ```

4. Done! System automatically handles deployment order.

## Technical Implementation

### Algorithms

**Topological Sort (Kahn's Algorithm)**:
```python
1. Build in-degree map (count of dependencies)
2. Start with services having 0 dependencies
3. Process in order, reducing in-degree of dependents
4. If all services processed → valid order
5. If some remain → circular dependency detected
```

**Transitive Dependency Resolution**:
```python
1. Start with target service
2. Visit each dependency recursively
3. Add to list after visiting its dependencies
4. Result: bottom-up installation order
```

### Error Handling

- **Cluster Down**: Returns 503 before checking dependencies
- **Already Deployed**: Informs user service exists
- **Circular Dependencies**: Detected at startup, prevents invalid graphs
- **Deployment Failure**: Stops chain, reports which service failed
- **Missing Manifest**: Clear error about missing YAML file

## Files Changed/Created

### Created:
- `backend/src/models/service_dependency.py` - DB model
- `backend/src/utils/dependencies.py` - Dependency resolver (310 lines)

### Modified:
- `backend/src/models/__init__.py` - Added model imports
- `backend/src/api/services.py` - Added deployment-plan endpoint, updated deploy logic
- `frontend/src/pages/Services.jsx` - Added deployment plan modal
- `backend/deployments/README.md` - Added dependency documentation

## Benefits

1. **User Experience**:
   - No manual dependency management
   - Clear visibility of what will be installed
   - Prevents deployment failures from missing dependencies

2. **Developer Experience**:
   - Simple configuration (one line per dependency)
   - Automatic order resolution
   - Easy to add new services

3. **System Reliability**:
   - Prevents invalid states (service without dependencies)
   - Circular dependency detection
   - Transaction-like deployment (all or nothing per service)

4. **Maintainability**:
   - Centralized dependency configuration
   - Self-documenting (dependencies visible in code)
   - Easy to test and validate

## Future Enhancements

1. **Runtime Configuration**: Store dependencies in database for dynamic updates
2. **Parallel Deployment**: Deploy independent services simultaneously
3. **Rollback**: Automatic rollback if any service in chain fails
4. **Versioning**: Track compatible versions of dependencies
5. **Health Checks**: Wait for service to be healthy before deploying dependents
6. **UI Graph View**: Visual dependency graph in frontend
7. **Partial Deployment**: Allow user to select which dependencies to skip (if already installed elsewhere)

## Testing

To test the implementation:

1. **Start with clean cluster** (no services deployed)

2. **Try to deploy Schema Registry**:
   - Should show "Will install 1 dependency"
   - Should deploy Kafka first, then Schema Registry

3. **Try to deploy Kafka Connect**:
   - If Kafka not deployed: Should show "Will install 2 dependencies"
   - If Kafka deployed: Should show "Will install 1 dependency" (Schema Registry)

4. **Verify installation order**:
   - Check Kubernetes: `kubectl get pods -n streamlink`
   - Check UI: Services should appear in order
   - Check logs: Backend should log deployment sequence

## Conclusion

The service dependency management system provides a robust, user-friendly way to handle complex service deployments. It eliminates manual dependency tracking, prevents errors, and makes the system more scalable for adding new services.
