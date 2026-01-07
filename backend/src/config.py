"""Application configuration."""
from pydantic_settings import BaseSettings
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
    DEBUG: bool = True  # Default to True for development
    LOG_LEVEL: str = "info"

    # Database Configuration
    # Non-sensitive parts are here, password comes from env var
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "streamlink"
    DB_USER: str = "streamlink"
    DB_PASSWORD: str = ""  # MUST be set via POSTGRES_PASSWORD env var
    
    @property
    def DATABASE_URL(self) -> str:
        """Construct database URL from components."""
        password = os.getenv("POSTGRES_PASSWORD", self.DB_PASSWORD)
        return f"postgresql+asyncpg://{self.DB_USER}:{password}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    # Keycloak Configuration (non-sensitive)
    KEYCLOAK_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "streamlink"
    KEYCLOAK_CLIENT_ID: str = "streamlink-api"
    KEYCLOAK_CLIENT_SECRET: str = ""  # MUST be set via env var
    KEYCLOAK_REDIRECT_URI: str = "http://localhost:3001/auth/callback"

    # JWT Configuration
    JWT_ALGORITHM: str = "RS256"
    JWT_ACCESS_TOKEN_EXPIRY: int = 900  # 15 minutes
    JWT_REFRESH_TOKEN_EXPIRY: int = 604800  # 7 days

    # CORS Configuration
    CORS_ORIGINS: List[str] = [
        "http://localhost:3001",
        "http://localhost:3000",
        "https://streamlink.example.com",
    ]
    ALLOWED_HOSTS: List[str] = ["*"]

    # Kubernetes Configuration
    KUBECONFIG_PATH: str = "~/.kube/config"

    # Kafka Configuration (OPTIONAL - User configures via UI)
    KAFKA_BOOTSTRAP_SERVERS: Optional[str] = None
    KAFKA_SECURITY_PROTOCOL: str = "PLAINTEXT"

    # Logging Configuration
    STRUCTLOG_JSON_LOGS: bool = True
    
    # Encryption (Secret - MUST be set via env var)
    ENCRYPTION_KEY: str = ""  # MUST be set via env var

    class Config:
        env_file = ".env"
        case_sensitive = True
        case_sensitive = True


settings = Settings()
