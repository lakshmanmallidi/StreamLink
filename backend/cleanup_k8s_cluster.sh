#!/bin/bash
# StreamLink Cleanup Script
# Removes all Kubernetes resources from the streamlink namespace

set -e

NAMESPACE="streamlink"

echo "🧹 StreamLink Cleanup Script"
echo "=============================="
echo ""
echo "This will DELETE all resources in the '$NAMESPACE' namespace:"
echo "  - Pods, Deployments, StatefulSets"
echo "  - Services (ClusterIP and NodePort)"
echo "  - Secrets"
echo "  - PersistentVolumeClaims"
echo "  - ConfigMaps"
echo "  - And any other resources"
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm

if [ "$confirm" != "yes" ]; then
    echo "Cleanup cancelled."
    exit 0
fi

echo ""
echo "Starting cleanup..."

# Check if namespace exists
if ! kubectl get namespace $NAMESPACE &> /dev/null; then
    echo "✓ Namespace '$NAMESPACE' does not exist. Nothing to clean up."
    exit 0
fi

# Method 1: Delete the entire namespace (cleanest approach)
echo ""
echo "Deleting namespace '$NAMESPACE' (this removes everything)..."
kubectl delete namespace $NAMESPACE --timeout=60s

echo ""
echo "✅ Cleanup complete!"
echo ""
echo "Optional: Clean up local SQLite database:"
echo "  rm -f backend/bootstrap.db"
echo ""
