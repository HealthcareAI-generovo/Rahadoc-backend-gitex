"""
Shared dependencies for FastAPI routes.
Provides auth verification and database session management.
"""
from fastapi import Header, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Annotated

from app.config import settings
from app.db.session import get_db


async def verify_internal_secret(
    x_internal_secret: Annotated[str, Header()]
) -> None:
    """
    Verify that the request comes from the Next.js backend.
    All AI endpoints must include the X-Internal-Secret header.
    """
    if x_internal_secret != settings.INTERNAL_API_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid internal secret"
        )


async def verify_cron_secret(
    x_cron_secret: Annotated[str, Header()]
) -> None:
    """
    Verify that the request comes from Railway cron service.
    Only used for the alerts processing endpoint.
    """
    if not settings.CRON_SECRET or x_cron_secret != settings.CRON_SECRET:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized: Invalid cron secret"
        )


# Type aliases for dependency injection
InternalAuth = Annotated[None, Depends(verify_internal_secret)]
CronAuth = Annotated[None, Depends(verify_cron_secret)]
DbSession = Annotated[AsyncSession, Depends(get_db)]
