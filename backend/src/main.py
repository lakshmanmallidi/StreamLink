"""FastAPI application factory and configuration."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api import health, auth_simple, clusters, services
from src.database import init_db
from src.config import settings


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="StreamLink API",
        description="Event orchestration control plane",
        version="1.0.0",
    )

    # Middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(health.router)
    app.include_router(auth_simple.router)
    app.include_router(clusters.router)
    app.include_router(services.router)

    @app.on_event("startup")
    async def startup_event():
        """Initialize database on startup."""
        await init_db()

    return app


if __name__ == "__main__":
    import uvicorn
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=3000)