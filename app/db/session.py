"""
SQLAlchemy async database session for accessing shared PostgreSQL.
"""
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import logging

from app.config import settings

logger = logging.getLogger(__name__)

def _normalize_database_url(raw_url: str) -> str:
    """
    Convert PostgreSQL URLs to SQLAlchemy asyncpg format and remove
    Prisma-specific params unsupported by SQLAlchemy DBAPI connectors.
    """
    # Accept both postgresql:// and postgres:// forms.
    if raw_url.startswith("postgresql+asyncpg://"):
        normalized = raw_url
    elif raw_url.startswith("postgresql://"):
        normalized = raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif raw_url.startswith("postgres://"):
        normalized = raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
    else:
        normalized = raw_url

    # Prisma commonly appends ?schema=public. SQLAlchemy DB drivers don't support
    # this query argument and may raise: connect() got an unexpected keyword arg.
    parts = urlsplit(normalized)
    if parts.query:
        filtered_params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() != "schema"]
        normalized_query = urlencode(filtered_params, doseq=True)
        normalized = urlunsplit((parts.scheme, parts.netloc, parts.path, normalized_query, parts.fragment))

    return normalized


database_url = _normalize_database_url(settings.DATABASE_URL)

# Create async engine
engine = create_async_engine(
    database_url,
    poolclass=NullPool,  # Use NullPool for Railway's connection limits
    echo=settings.DEBUG,
)

# Create sessionmaker
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncSession:
    """
    Dependency for FastAPI routes to get database session.

    Usage:
        @app.get("/example")
        async def example(db: DbSession):
            # Use db here
            pass
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()
