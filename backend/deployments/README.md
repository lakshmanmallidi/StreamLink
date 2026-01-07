# Kubernetes Deployment Manifests

This directory contains Kubernetes YAML manifests for deploying services to the connected cluster.

## Structure

Each service has its own YAML file containing all necessary Kubernetes resources:
- Namespace (if needed)
- Deployment
- Service
- ConfigMap (if needed)
- Secret (if needed)

## Available Services

### Schema Registry (`schema-registry.yaml`)
- **Image**: confluentinc/cp-schema-registry:7.5.0
- **Namespace**: streamlink
- **Port**: 8081
- **Resources**: 512Mi-1Gi memory, 250m-500m CPU
- **Features**: Liveness/Readiness probes configured

### Kafka (`kafka.yaml`)
- **Image**: confluentinc/cp-kafka:7.5.0
- **Namespace**: streamlink
- **Port**: 9092 (client), 9093 (controller)
- **Mode**: KRaft (no Zookeeper required)
- **Resources**: 1Gi-2Gi memory, 500m-1000m CPU

## How It Works

1. **Backend reads YAML**: When deploying a service, the backend reads the corresponding YAML file
2. **Namespace substitution**: If a custom namespace is specified, it replaces `streamlink` with the custom namespace
3. **Kubernetes API**: Uses the Python Kubernetes client to apply the manifest
4. **Resource management**: Handles creation and updates (idempotent)

## Adding New Services

To add a new service:

1. Create a new YAML file: `<service-name>.yaml`
2. Include all necessary Kubernetes resources
3. Use `namespace: streamlink` (will be replaced if needed)
4. Add resource requests/limits
5. Configure health checks (liveness/readiness probes)
6. Update the frontend `Services.jsx` to add the service to the available list

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
