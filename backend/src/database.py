"""Database initialization and ORM setup."""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import DeclarativeBase
import os
import sqlite3

from src.config import settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


def _check_postgres_deployed() -> tuple[bool, str | None, str | None, str | None]:
    """Check if Postgres is deployed AND migration is complete.
    Returns (migrated, encrypted_password, external_host, external_port)
    
    Important: Backend only switches to Postgres after migration is complete,
    not just when Postgres is deployed.
    """
    db_path = os.path.join(os.path.dirname(__file__), "..", "bootstrap.db")
    
    if not os.path.exists(db_path):
        return False, None, None, None
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT postgres_deployed, migration_complete, postgres_admin_password, postgres_external_host, postgres_external_port FROM bootstrap_state LIMIT 1"
        )
        row = cursor.fetchone()
        conn.close()
        
        # Only return True if BOTH postgres is deployed AND migration is complete
        if row and row[0] and row[1]:  # postgres_deployed AND migration_complete
            return True, row[2], row[3], row[4]  # encrypted password, host, port
    except Exception:
        pass
    
    return False, None, None, None


def get_database_url() -> str:
    """Get database URL - SQLite for bootstrap, Postgres after migration.
    
    Database switching logic:
    1. SQLite (bootstrap.db) - Initial state, used to store cluster config and deploy Postgres
    2. Postgres - Only after Postgres is deployed AND migration is complete
    """
    # Check if migration to Postgres is complete
    postgres_migrated, encrypted_password, external_host, external_port = _check_postgres_deployed()
    
    if not postgres_migrated:
        # Use SQLite for bootstrap (to store cluster config for deploying Postgres)
        db_path = os.path.join(os.path.dirname(__file__), "..", "bootstrap.db")
        return f"sqlite+aiosqlite:///{db_path}"
    else:
        # Backend runs locally, use external NodePort to connect to Postgres
        from src.utils.crypto import get_crypto_service
        from src.config import settings
        from urllib.parse import quote_plus
        
        crypto = get_crypto_service()
        password = crypto.decrypt(encrypted_password)
        
        # URL-encode password to handle special characters
        encoded_password = quote_plus(password)
        
        # Use external NodePort (backend runs outside Kubernetes)
        host = external_host or "localhost"
        port = external_port or str(settings.POSTGRES_NODEPORT)
        user = "postgres"
        dbname = "streamlink"  # Dedicated StreamLink database
        
        return f"postgresql+asyncpg://{user}:{encoded_password}@{host}:{port}/{dbname}"


# Create async engine
engine = create_async_engine(
    get_database_url(),
    echo=False,  # Disable SQL echo to prevent logging
    pool_pre_ping=True,
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Flag to track if we've fallen back to SQLite
_fallback_to_sqlite = False


async def get_db() -> AsyncSession:
    """Dependency for getting async database session with automatic fallback."""
    global engine, AsyncSessionLocal, _fallback_to_sqlite
    
    # Test connection before yielding if using Postgres
    current_url = str(engine.url)
    if "postgresql" in current_url and not _fallback_to_sqlite:
        try:
            # Try to get a connection to test if Postgres is available
            async with engine.connect() as conn:
                pass  # Connection works
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Postgres connection failed: {type(e).__name__}: {str(e)[:100]}")
            logger.warning("Falling back to SQLite - please restart backend for stable operation")
            
            _fallback_to_sqlite = True
            
            # Recreate engine with SQLite
            db_path = os.path.join(os.path.dirname(__file__), "..", "bootstrap.db")
            sqlite_url = f"sqlite+aiosqlite:///{db_path}"
            
            engine = create_async_engine(sqlite_url, echo=False, pool_pre_ping=True)
            AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
            
            logger.info("Switched to SQLite successfully")
    
    # Now yield the session (with fallback already applied if needed)
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Initialize database tables."""
    import logging
    logger = logging.getLogger(__name__)
    
    postgres_migrated, _, _, _ = _check_postgres_deployed()
    db_type = "PostgreSQL" if postgres_migrated else "SQLite (bootstrap)"
    logger.info(f"Initializing database: {db_type}")
    
    try:
        # Import models to register with Base
        import src.models  # noqa: F401
        
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info(f"Database tables initialized successfully ({db_type})")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise
