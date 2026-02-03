"""OAuth Client model for storing Keycloak client credentials."""
from sqlalchemy import Column, String, DateTime, Boolean, Text
from sqlalchemy.sql import func
from src.database import Base
from src.models.types import GUID
import uuid


class OAuthClient(Base):
    """Stores OAuth client credentials for Keycloak integration.
    
    Client secrets are stored encrypted using the ENCRYPTION_KEY from config.
    """
    __tablename__ = "oauth_clients"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    client_id = Column(String(255), unique=True, nullable=False, index=True)
    client_secret = Column(Text, nullable=False)  # Encrypted
    realm = Column(String(255), nullable=False, default="streamlink")
    redirect_uris = Column(Text)  # JSON array stored as text
    description = Column(Text)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<OAuthClient(client_id='{self.client_id}', realm='{self.realm}')>"
