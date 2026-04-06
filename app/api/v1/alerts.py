"""
Smart Alerts API endpoints.
"""
from fastapi import APIRouter, HTTPException
import logging

from app.dependencies import CronAuth, DbSession
from app.models.alerts import AlertProcessRequest, AlertProcessResponse
from app.services.alerts_engine import alerts_engine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/process", response_model=AlertProcessResponse)
async def process_alerts(
    _: CronAuth,
    db: DbSession,
    request: AlertProcessRequest
):
    """
    Process smart alerts (cron endpoint).

    Protected by X-Cron-Secret header.
    Called by Railway cron scheduler.
    """
    try:
        logger.info(f"Processing alerts via cron (cabinet: {request.cabinet_id or 'ALL'})")

        processed_count, new_alerts, skipped = await alerts_engine.process_alerts(
            db=db,
            cabinet_id=request.cabinet_id
        )

        return AlertProcessResponse(
            processed_count=processed_count,
            new_alerts=new_alerts,
            skipped_duplicates=skipped
        )

    except Exception as e:
        logger.error(f"Alert processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
