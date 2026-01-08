# Kubernetes Deployment Manifests

This directory contains Kubernetes YAML manifests for deploying services to the connected cluster.

## Structure

Each service has its own YAML file containing all necessary Kubernetes resources:
- Namespace (if needed)
- Deployment
- Service
- ConfigMap (if needed)
- Secret (if needed)

## Service Dependency Management

StreamLink automatically handles service dependencies:

**Dependency Graph:**
- `kafka` → No dependencies
- `schema-registry` → Depends on `kafka`
- `kafka-connect` → Depends on `kafka`, `schema-registry`
- `ksqldb` → Depends on `kafka`
- `kafka-rest` → Depends on `kafka`, `schema-registry`

When deploying a service, StreamLink will:
1. Check which dependencies are missing
2. Show a deployment plan to the user
3. Install dependencies in the correct order
4. Finally install the target service

## Available Services

### Kafka (`kafka.yaml`)
- **Image**: confluentinc/cp-kafka:7.5.0
- **Namespace**: streamlink
- **Port**: 9092 (client), 9093 (controller)
- **Mode**: KRaft (no Zookeeper required)
- **Resources**: 1Gi-2Gi memory, 500m-1000m CPU
- **Dependencies**: None (base service)

### Schema Registry (`schema-registry.yaml`)
- **Image**: confluentinc/cp-schema-registry:7.5.0
- **Namespace**: streamlink
- **Port**: 8081
- **Resources**: 512Mi-1Gi memory, 250m-500m CPU
- **Dependencies**: Kafka
- **Features**: Liveness/Readiness probes configured

## How It Works

1. **Backend reads YAML**: When deploying a service, the backend reads the corresponding YAML file
2. **Dependency resolution**: Checks for missing dependencies and resolves installation order
3. **Namespace substitution**: If a custom namespace is specified, it replaces `streamlink` with the custom namespace
4. **Kubernetes API**: Uses the Python Kubernetes client to apply the manifest
5. **Resource management**: Handles creation and updates (idempotent)

## Adding New Services

To add a new service:

1. **Create YAML manifest**: `<service-name>.yaml`
   - Include all necessary Kubernetes resources
   - Use `namespace: streamlink` (will be replaced if needed)
   - Add resource requests/limits
   - Configure health checks (liveness/readiness probes)
   - Add init containers for dependency checks if needed

2. **Update dependency graph** in `backend/src/utils/dependencies.py`:
   ```python
   SERVICE_DEPENDENCIES = {
       ...
       "my-service": ["kafka"],  # Add dependencies
   }
   
   SERVICE_DISPLAY_NAMES = {
       ...
       "my-service": "My Service",
   }
   ```

3. **Update frontend** `frontend/src/pages/Services.jsx`:
   ```javascript
   const availableServices = [
     ...
     {
       name: "my-service",
       displayName: "My Service",
       description: "Description here. Requires Kafka.",
       icon: "🎯",
       dependencies: ["kafka"],
     },
   ];
   ```

4. **Test deployment**:
   - Start backend and frontend
   - Try deploying with and without dependencies installed
   - Verify deployment plan shows correctly

Example structure:
```yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: my-service
  namespace: streamlink
  labels:
    app: my-service
spec:
  replicas: 1
  selector:
    matchLabels:
      app: my-service
  template:
    metadata:
      labels:
        app: my-service
    spec:
      containers:
      - name: my-service
        image: my-org/my-service:latest
        ports:
        - containerPort: 8080
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "200m"
---
apiVersion: v1
kind: Service
metadata:
  name: my-service
  namespace: streamlink
spec:
  type: ClusterIP
  ports:
  - port: 8080
    targetPort: 8080
  selector:
    app: my-service
```

## Updating Services

To update a service configuration:
1. Edit the YAML file directly
2. Restart the backend (or it will auto-reload in dev mode)
3. Redeploy from the UI or API

No code changes required!

## Testing Manifests

You can test manifests manually using kubectl:
```bash
kubectl apply -f schema-registry.yaml
kubectl get pods -n streamlink
kubectl delete -f schema-registry.yaml
```

## Best Practices

- Always specify resource requests and limits
- Configure liveness and readiness probes
- Use specific image tags (not `latest`)
- Include labels for easy filtering
- Document environment variables
- Use ConfigMaps for non-sensitive config
- Use Secrets for sensitive data
