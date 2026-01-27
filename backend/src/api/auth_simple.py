"""Simple authentication endpoints."""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import httpx
import jwt
from datetime import datetime
import hashlib
import base64
import secrets

from src.database import get_db, get_database_url
from src.config import settings
from src.models.user import User
from src.models.bootstrap_state import BootstrapState
from sqlalchemy.future import select

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


class CallbackRequest(BaseModel):
    code: str
    code_verifier: str


class TokenResponse(BaseModel):
    access_token: str
    user: dict


async def is_keycloak_deployed(db: AsyncSession) -> bool:
    """Check if Keycloak is deployed by checking services table.
    
    If Postgres is not deployed, Keycloak cannot be deployed (dependency rule).
    """
    from src.models.service import Service
    
    # Check if Postgres is deployed first (dependency requirement)
    stmt = select(BootstrapState)
    result = await db.execute(stmt)
    bootstrap_state = result.scalar_one_or_none()
    
    if not bootstrap_state or not bootstrap_state.postgres_deployed:
        return False
    
    # Check if Keycloak service exists and is active
    stmt = select(Service).where(
        Service.manifest_name == "keycloak",
        Service.is_active == True
    )
    result = await db.execute(stmt)
    keycloak_service = result.scalar_one_or_none()
    
    return keycloak_service is not None


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
    )
    
    return {
        "login_url": login_url,
        "code_verifier": code_verifier
    }


@router.post("/callback")
async def oauth_callback(request: CallbackRequest, db: AsyncSession = Depends(get_db)):
    """Exchange authorization code for access token."""
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
        
        # Exchange code for token with Keycloak
        token_url = f"{keycloak_url}/realms/{realm}/protocol/openid-connect/token"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.KEYCLOAK_STREAMLINK_API_CLIENT_ID,
                    "client_secret": settings.KEYCLOAK_STREAMLINK_API_CLIENT_SECRET,
                    "code": request.code,
                    "code_verifier": request.code_verifier,
                    "redirect_uri": settings.KEYCLOAK_STREAMLINK_API_REDIRECT_URI,
                },
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=401, detail="Invalid authorization code")
            
            tokens = response.json()
        
        # Decode token (without signature verification for now)
        decoded = jwt.decode(
            tokens["access_token"],
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
    """Simple login without Keycloak (only works when Keycloak is not deployed)."""
    keycloak_deployed = await is_keycloak_deployed(db)
    
    if keycloak_deployed:
        raise HTTPException(
            status_code=403,
            detail="Simple login is disabled. Use Keycloak authentication."
        )
    
    # Create or get anonymous user
    stmt = select(User).where(User.username == "admin")
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        user = User(
            keycloak_id="local-admin",
            username="admin",
            email="admin@streamlink.local",
            is_active=True
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    
    # Generate a simple token
    token = f"simple-token-{user.id}"
    
    return TokenResponse(
        access_token=token,
        user={
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "keycloak_id": user.keycloak_id,
        }
    )


@router.post("/logout")
async def logout():
    """Logout endpoint."""
    return {"message": "Logged out"}
