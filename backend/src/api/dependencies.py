"""Authentication dependencies for protecting API endpoints."""
from fastapi import Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging

from src.database import get_db
from src.models.bootstrap_state import BootstrapState
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def is_keycloak_deployed(db: AsyncSession) -> bool:
    """Check if Keycloak is deployed and OAuth is active."""
    stmt = select(BootstrapState)
    result = await db.execute(stmt)
    bootstrap_state = result.scalar_one_or_none()
    
    if not bootstrap_state:
        return False
    
    return bootstrap_state.keycloak_deployed


async def verify_authentication(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Verify authentication based on deployment status.
    
    - If Keycloak is deployed: Only accept valid Keycloak JWT tokens
    - If Keycloak is not deployed: Accept simple tokens or no auth
    """
    keycloak_deployed = await is_keycloak_deployed(db)
    
    if keycloak_deployed:
        # Keycloak is deployed - MUST have valid JWT token
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=401,
                detail="Authentication required. Please login via Keycloak."
            )
        
        token = authorization.replace("Bearer ", "")
        
        # Reject simple tokens
        if token.startswith("simple-token-"):
            raise HTTPException(
                status_code=401,
                detail="Simple authentication is disabled. Please login via Keycloak."
            )
        
        # Validate Keycloak JWT token
        try:
            from src.utils.keycloak_admin import keycloak_admin
            # Verify token with Keycloak
            user_info = await keycloak_admin.verify_token(token)
            if not user_info:

                raise HTTPException(
                    status_code=401,
                    detail="Invalid or expired token. Please login again."
                )
            return user_info
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Token validation failed with error: {type(e).__name__}: {str(e)}")
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token. Please login again."
            )
    else:
        # Keycloak not deployed - allow simple tokens or no auth
        if authorization and authorization.startswith("Bearer "):
            token = authorization.replace("Bearer ", "")
            if token.startswith("simple-token-"):
                # Simple token is valid when Keycloak not deployed
                return {"sub": "anonymous", "username": "anonymous"}
        
        # No Keycloak, no strict auth required - allow anonymous access
        return {"sub": "anonymous", "username": "anonymous"}
