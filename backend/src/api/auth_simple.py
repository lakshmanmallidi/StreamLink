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

from src.database import get_db
from src.config import settings
from src.models.user import User
from sqlalchemy.future import select

router = APIRouter(prefix="/v1/auth", tags=["Auth"])


class CallbackRequest(BaseModel):
    code: str
    code_verifier: str


class TokenResponse(BaseModel):
    access_token: str
    user: dict


@router.get("/login-url")
async def get_login_url():
    """Get Keycloak login URL with PKCE."""
    # Generate PKCE
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode()).digest()
    ).decode().rstrip("=")
    
    login_url = (
        f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/auth"
        f"?client_id={settings.KEYCLOAK_CLIENT_ID}"
        f"&redirect_uri={settings.KEYCLOAK_REDIRECT_URI}"
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
        # Exchange code for token with Keycloak
        token_url = f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "client_id": settings.KEYCLOAK_CLIENT_ID,
                    "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
                    "code": request.code,
                    "code_verifier": request.code_verifier,
                    "redirect_uri": settings.KEYCLOAK_REDIRECT_URI,
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


@router.post("/logout")
async def logout():
    """Logout endpoint."""
    return {"message": "Logged out"}
