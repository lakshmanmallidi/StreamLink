"""Application configuration."""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Optional
import os


class Settings(BaseSettings):
    """Application settings.
    
    Non-sensitive configuration is defined here with sensible defaults.
    Secrets (passwords, keys, tokens) are loaded from environment variables.
    
    Priority: Environment variables > .env file > defaults defined here
    """

    # App Configuration
    APP_NAME: str = "StreamLink"
    APP_VERSION: str = "1.0.0"

    # External NodePort Configuration (for services exposed outside Kubernetes)
    POSTGRES_NODEPORT: int = 30432
    KEYCLOAK_NODEPORT: int = 30081
    KAFBAT_UI_NODEPORT: int = 30080

    # CORS Configuration (exact origins with protocol)
    CORS_ORIGINS: List[str] = [
        "http://localhost:3001",
        "http://localhost:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3000",
    ]
    ALLOWED_HOSTS: List[str] = ["*"]
    
    # Encryption (Secret - MUST be set via env var)
    ENCRYPTION_KEY: str = Field(default="", json_schema_extra={'secret': True})  # MUST be set via env var
    
    # Keycloak OAuth Client Configuration (for StreamLink API)
    KEYCLOAK_STREAMLINK_API_CLIENT_ID: str = "streamlink-api"
    KEYCLOAK_STREAMLINK_API_REDIRECT_URI: str = "http://localhost:3001/auth/callback"
    KEYCLOAK_STREAMLINK_API_POST_LOGOUT_URI: str = "http://localhost:3001/login"
    
    # Keycloak OAuth Client Configuration (for Kafbat UI)
    KEYCLOAK_KAFBAT_UI_CLIENT_ID: str = "kafbat-ui"

    # Keycloak Issuer URI (for OIDC discovery used by Kafbat UI)
    # Use internal service URL so in-cluster apps can reach it
    KEYCLOAK_ISSUER_URI: str = "http://keycloak.streamlink.svc.cluster.local:8080/realms/streamlink"

    # External URLs for Kafbat UI will be computed from cluster node IPs
    # during deployment, not from static app settings.

    class Config:
        env_file = ".env"
        case_sensitive = True
        case_sensitive = True


settings = Settings()
