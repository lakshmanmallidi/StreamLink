"""User database model."""
from sqlalchemy import Column, String, DateTime, Boolean
import uuid
from datetime import datetime

from src.database import Base
from src.models.types import GUID


class User(Base):
    """User model for storing authenticated user information."""
    __tablename__ = "users"

    id = Column(GUID, primary_key=True, default=uuid.uuid4)
    keycloak_id = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)  # Optional for service accounts
    username = Column(String(255), nullable=False)
    first_name = Column(String(255))
    last_name = Column(String(255))
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "id": str(self.id),
            "keycloak_id": self.keycloak_id,
            "email": self.email,
            "username": self.username,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "is_active": self.is_active,
        }
