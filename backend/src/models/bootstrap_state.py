"""Bootstrap state model for tracking Postgres deployment only."""
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from src.database import Base
import uuid


class BootstrapState(Base):
    """Track bootstrap deployment state for Postgres only.
    
    Architecture:
    - SQLite mode: Tracks Postgres deployment status and credentials
    - After Postgres migration: This table moves to Postgres
    
    Flow:
    1. Start with SQLite, deploy Postgres → Postgres fields populated
    2. Migrate to Postgres → Bootstrap state moves to Postgres
    """
    __tablename__ = "bootstrap_state"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Deployment status flags
    postgres_deployed = Column(Boolean, default=False)
    migration_complete = Column(Boolean, default=False)
    
    # Encrypted credentials (stored encrypted with ENCRYPTION_KEY)
    postgres_admin_password = Column(String, nullable=True)
    
    # Internal Kubernetes service endpoints (ClusterIP services)
    postgres_internal_host = Column(String, default="postgres.streamlink.svc.cluster.local")
    postgres_internal_port = Column(String, default="5432")
    
    # External Kubernetes service endpoints (NodePort services)
    postgres_external_host = Column(String, nullable=True)  # Will be node IP
    postgres_external_port = Column(String, default="30432")  # NodePort
    
    # Legacy fields for backward compatibility
    postgres_host = Column(String, nullable=True)
    postgres_port = Column(String, default="5432")
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
