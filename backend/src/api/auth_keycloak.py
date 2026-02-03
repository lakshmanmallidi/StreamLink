"""Keycloak OAuth authentication endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
import httpx
import secrets
from typing import Optional

from src.database import get_db
from src.models.oauth_client import OAuthClient
from src.models.user import User
from src.models.service import Service
from src.utils.crypto import get_crypto_service
from src.config import settings

router = APIRouter(prefix="/v1/auth/keycloak", tags=["Authentication"])


# In-memory state storage (in production, use Redis or database)
_oauth_states = {}


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    refresh_token: Optional[str] = None
    scope: Optional[str] = None


@router.get("/login")
async def keycloak_login(db: AsyncSession = Depends(get_db)):
    """Initiate OAuth2 login flow with Keycloak.
    
    Redirects user to Keycloak login page.
    """
    # Get streamlink-api client from database
    stmt = select(OAuthClient).where(
        OAuthClient.client_id == settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID,
        OAuthClient.is_active == True
    )
    result = await db.execute(stmt)
    oauth_client = result.scalar_one_or_none()
    
    if not oauth_client:
        raise HTTPException(
            status_code=500,
            detail="OAuth client not configured. Deploy Keycloak first."
        )
    
    # Get Keycloak service info for external URL
    keycloak_svc = await db.execute(select(Service).where(Service.name == "keycloak"))
    keycloak = keycloak_svc.scalar_one_or_none()
    if not keycloak or not keycloak.external_host:
        raise HTTPException(status_code=500, detail="Keycloak service not properly configured")
    
    # Generate state parameter for CSRF protection
    state = secrets.token_urlsafe(32)
    _oauth_states[state] = {"created": True}
    
    # Build Keycloak authorization URL using external host
    keycloak_base_url = f"http://{keycloak.external_host}:{keycloak.external_port}"
    auth_url = (
        f"{keycloak_base_url}/realms/{oauth_client.realm}/protocol/openid-connect/auth"
        f"?client_id={oauth_client.client_id}"
        f"&redirect_uri={settings.KEYCLOAK_STREAMLINK_API_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid email profile"
        f"&state={state}"
    )
    
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def keycloak_callback(
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db)
):
    """Handle OAuth2 callback from Keycloak.
    
    Exchanges authorization code for access token.
    """
    # Validate state parameter
    if state not in _oauth_states:
        raise HTTPException(status_code=400, detail="Invalid state parameter")
    
    # Remove used state
    del _oauth_states[state]
    
    # Get streamlink-api client from database
    stmt = select(OAuthClient).where(
        OAuthClient.client_id == settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID,
        OAuthClient.is_active == True
    )
    result = await db.execute(stmt)
    oauth_client = result.scalar_one_or_none()
    
    if not oauth_client:
        raise HTTPException(status_code=500, detail="OAuth client not configured")
    
    # Get Keycloak service info for external URL
    keycloak_svc = await db.execute(select(Service).where(Service.name == "keycloak"))
    keycloak = keycloak_svc.scalar_one_or_none()
    if not keycloak or not keycloak.external_host:
        raise HTTPException(status_code=500, detail="Keycloak service not properly configured")
    
    # Decrypt client secret
    crypto = get_crypto_service()
    try:
        client_secret = crypto.decrypt(oauth_client.client_secret)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt client secret: {str(e)}")
    
    # Exchange authorization code for tokens using external host
    keycloak_base_url = f"http://{keycloak.external_host}:{keycloak.external_port}"
    token_url = f"{keycloak_base_url}/realms/{oauth_client.realm}/protocol/openid-connect/token"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.KEYCLOAK_STREAMLINK_API_REDIRECT_URI,
                "client_id": oauth_client.client_id,
                "client_secret": client_secret
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
    
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Token exchange failed: {response.text}"
        )
    
    token_data = response.json()
    
    # Get user info
    userinfo_url = f"{keycloak_base_url}/realms/{oauth_client.realm}/protocol/openid-connect/userinfo"
    async with httpx.AsyncClient() as client:
        userinfo_response = await client.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {token_data['access_token']}"}
        )
    
    if userinfo_response.status_code == 200:
        user_info = userinfo_response.json()
        
        # Create or update user in database
        email = user_info.get("email")
        if email:
            stmt = select(User).where(User.email == email)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                user = User(
                    email=email,
                    username=user_info.get("preferred_username", email.split("@")[0]),
                    is_active=True
                )
                db.add(user)
                await db.commit()
    
    # Return tokens (in production, you'd set secure HTTP-only cookies)
    return TokenResponse(
        access_token=token_data["access_token"],
        token_type=token_data.get("token_type", "Bearer"),
        expires_in=token_data.get("expires_in", 300),
        refresh_token=token_data.get("refresh_token"),
        scope=token_data.get("scope")
    )


@router.post("/refresh")
async def refresh_token(
    refresh_token: str,
    db: AsyncSession = Depends(get_db)
):
    """Refresh access token using refresh token."""
    # Get streamlink-api client from database
    stmt = select(OAuthClient).where(
        OAuthClient.client_id == settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID,
        OAuthClient.is_active == True
    )
    result = await db.execute(stmt)
    oauth_client = result.scalar_one_or_none()
    
    if not oauth_client:
        raise HTTPException(status_code=500, detail="OAuth client not configured")
    
    # Get Keycloak service info for external URL
    keycloak_svc = await db.execute(select(Service).where(Service.name == "keycloak"))
    keycloak = keycloak_svc.scalar_one_or_none()
    if not keycloak or not keycloak.external_host:
        raise HTTPException(status_code=500, detail="Keycloak service not properly configured")
    
    # Decrypt client secret
    crypto = get_crypto_service()
    try:
        client_secret = crypto.decrypt(oauth_client.client_secret)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt client secret: {str(e)}")
    
    # Request new tokens using external host
    keycloak_base_url = f"http://{keycloak.external_host}:{keycloak.external_port}"
    token_url = f"{keycloak_base_url}/realms/{oauth_client.realm}/protocol/openid-connect/token"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": oauth_client.client_id,
                "client_secret": client_secret
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
    
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Token refresh failed: {response.text}"
        )
    
    token_data = response.json()
    
    return TokenResponse(
        access_token=token_data["access_token"],
        token_type=token_data.get("token_type", "Bearer"),
        expires_in=token_data.get("expires_in", 300),
        refresh_token=token_data.get("refresh_token"),
        scope=token_data.get("scope")
    )


@router.post("/logout")
async def keycloak_logout(
    refresh_token: str,
    db: AsyncSession = Depends(get_db)
):
    """Logout from Keycloak (revoke tokens)."""
    # Get streamlink-api client from database
    stmt = select(OAuthClient).where(
        OAuthClient.client_id == settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID,
        OAuthClient.is_active == True
    )
    result = await db.execute(stmt)
    oauth_client = result.scalar_one_or_none()
    
    if not oauth_client:
        raise HTTPException(status_code=500, detail="OAuth client not configured")
    
    # Get Keycloak service info for external URL
    keycloak_svc = await db.execute(select(Service).where(Service.name == "keycloak"))
    keycloak = keycloak_svc.scalar_one_or_none()
    if not keycloak or not keycloak.external_host:
        raise HTTPException(status_code=500, detail="Keycloak service not properly configured")
    
    # Decrypt client secret
    crypto = get_crypto_service()
    try:
        client_secret = crypto.decrypt(oauth_client.client_secret)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decrypt client secret: {str(e)}")
    
    # Revoke refresh token using external host
    keycloak_base_url = f"http://{keycloak.external_host}:{keycloak.external_port}"
    logout_url = f"{keycloak_base_url}/realms/{oauth_client.realm}/protocol/openid-connect/logout"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            logout_url,
            data={
                "client_id": oauth_client.client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
    
    if response.status_code not in [200, 204]:
        raise HTTPException(
            status_code=response.status_code,
            detail=f"Logout failed: {response.text}"
        )
    
    return {"message": "Logged out successfully"}
