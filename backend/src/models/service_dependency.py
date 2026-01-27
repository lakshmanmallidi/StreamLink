"""Service dependency model for tracking service dependencies."""
from sqlalchemy import Column, String, Integer
import uuid

from src.database import Base
from src.models.types import GUID


class ServiceDependency(Base):
    """Service dependency model to track which services depend on others."""
    
    __tablename__ = "service_dependencies"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    service_name = Column(String(255), nullable=False, index=True)  # Deployed name (e.g., "schemaregistry")
    depends_on = Column(String(255), nullable=False, index=True)  # Deployed name (e.g., "kafka")
    manifest_name = Column(String(255), nullable=True)  # Manifest filename (e.g., "schema-registry")
    depends_on_manifest = Column(String(255), nullable=True)  # Dependency manifest name (e.g., "kafka")
    order = Column(Integer, default=0)  # Order in dependency chain (0 = must install first)
