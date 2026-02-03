"""Bootstrap state model for tracking Postgres deployment only."""
from sqlalchemy import Column, String, Boolean, DateTime
from sqlalchemy.sql import func
from src.database import Base
import uuid


class BootstrapState(Base):
    """Track bootstrap deployment state for Postgres only.
    
    Simplified model - only tracks deployment status flags.
    Connection details and credentials are stored in the Service model.
    
    Architecture:
    - SQLite mode: Tracks Postgres deployment status
    - After Postgres migration: This table moves to Postgres
    
    Flow:
    1. Start with SQLite, deploy Postgres → postgres_deployed = True
    2. Migrate to Postgres → migration_complete = True
    """
    __tablename__ = "bootstrap_state"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # Deployment status flags - only these are needed
    postgres_deployed = Column(Boolean, default=False)
    keycloak_deployed = Column(Boolean, default=False)
    migration_complete = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
