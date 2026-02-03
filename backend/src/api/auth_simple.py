"""Simple authentication endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import jwt
from datetime import datetime, timedelta
import hashlib
import base64
import secrets
import logging
import time
from collections import defaultdict

from src.database import get_db, get_database_url
from src.config import settings
from src.models.user import User
from src.models.service import Service
from src.models.bootstrap_state import BootstrapState
from src.api.dependencies import verify_authentication
from sqlalchemy.future import select
import json

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/auth", tags=["Auth"])

# Issue #6: Track used authorization codes to prevent reuse
# In production, use Redis or a database table
_used_codes = {}  # {code: expiry_timestamp}
_code_lock = defaultdict(bool)  # Simple lock to prevent race conditions

def _cleanup_used_codes():
    """Remove expired codes from tracking."""
    current_time = time.time()
    expired = [code for code, expiry in _used_codes.items() if expiry < current_time]
    for code in expired:
        del _used_codes[code]
        if code in _code_lock:
            del _code_lock[code]

def _mark_code_used(code: str) -> bool:
    """Mark authorization code as used. Returns False if already used."""
    _cleanup_used_codes()
    
    if code in _used_codes:
        return False  # Already used
    
    if _code_lock[code]:  # Race condition check
        return False
    
    _code_lock[code] = True
    _used_codes[code] = time.time() + 600  # Expire after 10 minutes
    return True


class CallbackRequest(BaseModel):
    code: str
    code_verifier: str


class TokenResponse(BaseModel):
    access_token: str
    user: dict


async def is_keycloak_deployed(db: AsyncSession) -> bool:
    """Check if Keycloak is deployed and OAuth is active.
    
    Uses bootstrap_state.keycloak_deployed flag which is set after
    successful Keycloak realm initialization.
    """
    stmt = select(BootstrapState)
    result = await db.execute(stmt)
    bootstrap_state = result.scalar_one_or_none()
    
    if not bootstrap_state:
        return False
    
    return bootstrap_state.keycloak_deployed


@router.get("/login-url")
async def get_login_url(db: AsyncSession = Depends(get_db)):
    """Get Keycloak login URL with PKCE."""
    # Check if Keycloak is deployed
    if not await is_keycloak_deployed(db):
        raise HTTPException(
            status_code=503, 
            detail="Keycloak is not deployed. Deploy Keycloak via Services UI to enable authentication."
        )
    
    # Get Keycloak service config
    from src.models.service import Service
    import json
    
    stmt = select(Service).where(
        Service.manifest_name == "keycloak",
        Service.is_active == True
    )
    result = await db.execute(stmt)
    keycloak_service = result.scalar_one_or_none()
    
    if not keycloak_service or not keycloak_service.config:
        raise HTTPException(
            status_code=503,
            detail="Keycloak configuration not found"
        )
    
    config = json.loads(keycloak_service.config)
    keycloak_url = config.get("external_url")
    
    if not keycloak_url:
        raise HTTPException(
            status_code=503,
            detail="Keycloak external URL not configured"
        )
    
    realm = "streamlink"
    
    # Generate PKCE
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")
    
    auth_url = (
        f"{keycloak_url}/realms/{realm}/protocol/openid-connect/auth"
        f"?client_id={settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID}"
        f"&redirect_uri={settings.KEYCLOAK_STREAMLINK_API_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid profile email"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=S256"
        f"&prompt=login"
    )
    
    return {
        "login_url": auth_url,
        "code_verifier": code_verifier
    }


@router.post("/callback")
async def oauth_callback(request: CallbackRequest, db: AsyncSession = Depends(get_db)):
    """Exchange authorization code for access token."""
    logger.info(f"OAuth callback received - code: {request.code[:20]}..., verifier: {request.code_verifier[:20]}...")
    
    # Issue #6: Prevent authorization code reuse
    if not _mark_code_used(request.code):
        logger.warning(f"Authorization code already used: {request.code[:20]}...")
        raise HTTPException(
            status_code=400,
            detail="Authorization code has already been used"
        )
    
    try:
        # Get Keycloak URL from services table
        stmt = select(Service).where(
            Service.manifest_name == "keycloak",
            Service.is_active == True
        )
        result = await db.execute(stmt)
        keycloak_service = result.scalar_one_or_none()
        
        if not keycloak_service or not keycloak_service.config:
            raise HTTPException(
                status_code=503,
                detail="Keycloak not available"
            )
        
        config = json.loads(keycloak_service.config)
        keycloak_url = config.get("external_url")
        realm = config.get("realm", "streamlink")
        
        if not keycloak_url:
            raise HTTPException(
                status_code=503,
                detail="Keycloak external URL not configured"
            )
        
        # Get OAuth client secret from database
        from src.models.oauth_client import OAuthClient
        from src.utils.crypto import get_crypto_service
        
        stmt = select(OAuthClient).where(
            OAuthClient.client_id == settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID,
            OAuthClient.is_active == True
        )
        result = await db.execute(stmt)
        oauth_client = result.scalar_one_or_none()
        
        if not oauth_client:
            raise HTTPException(
                status_code=503,
                detail="OAuth client not configured"
            )
        
        # Decrypt client secret
        crypto = get_crypto_service()
        client_secret = crypto.decrypt(oauth_client.client_secret)
        
        # Exchange code for token with Keycloak
        token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID,
                    "client_secret": client_secret,
                    "code": request.code,
                    "code_verifier": request.code_verifier,
                    "redirect_uri": settings.KEYCLOAK_STREAMLINK_API_REDIRECT_URI,
                },
            )
            
            if response.status_code != 200:
                logger.error(f"Token exchange failed: {response.status_code} - {response.text}")
                raise HTTPException(status_code=401, detail="Invalid authorization code")
            
            tokens = response.json()
        
        # Decode token to check contents (without signature verification for now)
        access_token = tokens.get("access_token")
        if not access_token:
            raise HTTPException(status_code=500, detail="No access token received")
        
        decoded = jwt.decode(
            access_token,
            options={"verify_signature": False},
        )
        
        # Get or create user
        keycloak_id = decoded.get("sub")
        username = decoded.get("preferred_username")
        email = decoded.get("email")
        
        stmt = select(User).where(User.keycloak_id == keycloak_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            user = User(
                keycloak_id=keycloak_id,
                username=username,
                email=email,
                is_active=True
            )
            db.add(user)
            await db.commit()
        else:
            user.username = username
            user.email = email
            user.updated_at = datetime.utcnow()
            await db.commit()
        
        return TokenResponse(
            access_token=tokens["access_token"],
            user={
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "keycloak_id": user.keycloak_id,
                "id_token": tokens.get("id_token")  # Include id_token for logout
            }
        )
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Authentication failed: {str(e)}")


@router.get("/status")
async def get_auth_status(db: AsyncSession = Depends(get_db)):
    """Get authentication status and configuration."""
    from src.models.service import Service
    import json
    
    keycloak_deployed = await is_keycloak_deployed(db)
    
    keycloak_url = None
    if keycloak_deployed:
        stmt = select(Service).where(
            Service.manifest_name == "keycloak",
            Service.is_active == True
        )
        result = await db.execute(stmt)
        keycloak_service = result.scalar_one_or_none()
        
        if keycloak_service and keycloak_service.config:
            try:
                config = json.loads(keycloak_service.config)
                keycloak_url = config.get("external_url")
            except:
                pass
    
    return {
        "auth_enabled": keycloak_deployed,
        "keycloak_url": keycloak_url,
        "message": "Authentication enabled via Keycloak" if keycloak_deployed else "Running without authentication"
    }


@router.post("/simple-login")
async def simple_login(db: AsyncSession = Depends(get_db)):
    """Simple login without Keycloak (only works when Keycloak is not deployed).
    
    Returns a temporary token without creating any database entries.
    """
    keycloak_deployed = await is_keycloak_deployed(db)
    
    if keycloak_deployed:
        raise HTTPException(
            status_code=403,
            detail="Simple login is disabled. Use Keycloak authentication."
        )
    
    # No authentication - just return a temporary token
    # Don't create database entries
    token = "simple-token-anonymous"
    
    return TokenResponse(
        access_token=token,
        user={
            "id": "anonymous",
            "username": "anonymous",
            "email": "anonymous@local",
            "keycloak_id": "local-anonymous",
        }
    )



@router.get("/logout-url", dependencies=[Depends(verify_authentication)])
async def get_logout_url(id_token_hint: str = None, db: AsyncSession = Depends(get_db)):
    """Get Keycloak logout URL with id_token_hint.
    
    Requires authentication: User must have valid access_token to request logout URL.
    This prevents unauthenticated users from accessing the endpoint.
    """
    # Check if Keycloak is deployed
    if not await is_keycloak_deployed(db):
        return {"logout_url": None}
    
    # Validate id_token_hint by decoding JWT (don't verify signature for logout)
    # Since user already authenticated with access_token, we just need to check id_token structure
    if id_token_hint:
        try:
            # Decode JWT without signature verification (logout is not security critical)
            decoded = jwt.decode(id_token_hint, options={"verify_signature": False})
            
            # Basic validation: check it has required claims
            if not decoded.get("sub") or not decoded.get("iss"):
                logger.warning("Invalid id_token_hint: missing required claims")
                id_token_hint = None
            else:
                logger.info(f"Valid id_token_hint for user: {decoded.get('sub')}")
        except Exception as e:
            logger.warning(f"Failed to decode id_token_hint: {str(e)}")
            # Don't use invalid tokens
            id_token_hint = None
    
    # Get Keycloak service config
    stmt = select(Service).where(
        Service.manifest_name == "keycloak",
        Service.is_active == True
    )
    result = await db.execute(stmt)
    keycloak_service = result.scalar_one_or_none()
    
    if not keycloak_service or not keycloak_service.config:
        return {"logout_url": None}
    
    config = json.loads(keycloak_service.config)
    keycloak_url = config.get("external_url")
    realm = "streamlink"
    
    # Build logout URL with id_token_hint for proper session termination
    logout_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/logout"
    params = [
        f"post_logout_redirect_uri={settings.KEYCLOAK_STREAMLINK_API_POST_LOGOUT_URI}",
        f"client_id={settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID}"
    ]
    
    if id_token_hint:
        params.append(f"id_token_hint={id_token_hint}")
    
    logout_url = f"{logout_url}?{'&'.join(params)}"
    
    return {"logout_url": logout_url}
