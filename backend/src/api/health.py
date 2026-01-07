"""Health check endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from datetime import datetime

from src.database import get_db

router = APIRouter(tags=["System"])


@router.get("/health")
async def health_check():
    """Liveness probe - basic health check."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
    }


@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness probe - checks database connectivity."""
    try:
        # Test database connection
        await db.execute(text("SELECT 1"))
        
        return {
            "status": "ready",
            "checks": {
                "database": True,
                "idp": True,  # Keycloak connectivity check can be added later
            },
        }
    except Exception as e:
        return {
            "status": "not_ready",
            "error": str(e),
        }, 503