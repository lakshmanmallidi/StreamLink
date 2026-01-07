"""API route initialization."""
from . import health, auth_simple, clusters, services

__all__ = ["health", "auth_simple", "clusters", "services"]