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

    # CORS Configuration
    CORS_ORIGINS: List[str] = [
        "http://localhost:3001",
        "http://localhost:3000",
    ]
    ALLOWED_HOSTS: List[str] = ["*"]
    
    # Encryption (Secret - MUST be set via env var)
    ENCRYPTION_KEY: str = Field(default="", json_schema_extra={'secret': True})  # MUST be set via env var
    
    # Keycloak OAuth Client Configuration (for StreamLink API)
    KEYCLOAK_STREAMLINK_API_CLIENT_ID: str = "streamlink-api"
    KEYCLOAK_STREAMLINK_API_REDIRECT_URI: str = "http://localhost:3001/auth/callback"
    KEYCLOAK_STREAMLINK_API_CLIENT_SECRET: str = Field(default="", json_schema_extra={'secret': True})
    
    # Keycloak OAuth Client Configuration (for Kafbat UI)
    KEYCLOAK_KAFBAT_UI_CLIENT_ID: str = "kafbat-ui"
    KEYCLOAK_KAFBAT_UI_REDIRECT_URI: str = "http://localhost:30080/login"

    class Config:
        env_file = ".env"
        case_sensitive = True
        case_sensitive = True


settings = Settings()
