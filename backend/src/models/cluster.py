"""Cluster model."""
from sqlalchemy import Column, String, Boolean, DateTime, Text
from datetime import datetime
import uuid

from src.database import Base
from src.models.types import GUID


class Cluster(Base):
    """Kubernetes cluster model."""
    
    __tablename__ = "clusters"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False, unique=True)
    api_server = Column(String(512), nullable=False)
    kubeconfig = Column(Text, nullable=False)
    status = Column(String(50), default="unknown")  # up, down, unknown
    last_checked = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
