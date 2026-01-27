"""Service model for tracking deployed services."""
from sqlalchemy import Column, String, Boolean, DateTime, Text, ForeignKey
from datetime import datetime
import uuid

from src.database import Base
from src.models.types import GUID


class Service(Base):
    """Deployed service model (Kafka, Schema Registry, etc.)."""
    
    __tablename__ = "services"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    cluster_id = Column(GUID, ForeignKey("clusters.id"), nullable=False)
    name = Column(String(255), nullable=False)  # Actual deployed name in K8s (e.g., "schemaregistry")
    manifest_name = Column(String(255), nullable=True)  # Manifest filename (e.g., "schema-registry")
    display_name = Column(String(255), nullable=False)  # e.g., "Schema Registry"
    namespace = Column(String(255), default="default")
    status = Column(String(50), default="pending")  # pending, deploying, running, failed, stopped
    version = Column(String(50), nullable=True)
    replicas = Column(String(10), nullable=True)  # e.g., "1/1", "2/3"
    config = Column(Text, nullable=True)  # JSON config for the service
    last_checked = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
