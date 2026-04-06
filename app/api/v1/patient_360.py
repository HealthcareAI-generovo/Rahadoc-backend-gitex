"""
Patient 360 API endpoints.
"""
from fastapi import APIRouter, HTTPException
import logging
import json
from datetime import datetime

from app.dependencies import InternalAuth, DbSession
from app.models.patient_360 import Patient360Request, Patient360Response
from app.services.patient_360 import patient_360_service
from app.services.audit import audit_logger, AICallTimer
from app.db.queries import get_patient_context
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/summary", response_model=Patient360Response)
async def generate_patient_summary(
    _: InternalAuth,
    db: DbSession,
    request: Patient360Request
):
    """
    Generate AI-powered Patient 360 summary.

    Returns a comprehensive overview of patient's medical history.
    Results are cached for 24h unless force_regenerate is True.
    """
    try:
        logger.info(f"Generating Patient 360 for {request.patient_id}")

        # TODO: Check cache first (not implemented yet - would store in a patient360_cache JSON field)

        # Fetch patient data
        patient_ctx = await get_patient_context(db, request.patient_id, request.cabinet_id)

        # Generate summary
        with AICallTimer() as timer:
            summary = await patient_360_service.generate_summary(
                patient_data=patient_ctx["patient"],
                consultations=patient_ctx["consultations"],
                protocols=patient_ctx["protocols"],
                recent_measures=None  # TODO: Fetch recent measures
            )

        # Log to audit
        audit_id = await audit_logger.log_ai_call(
            db=db,
            cabinet_id=request.cabinet_id,
            action_type="SUMMARY",
            input_text=f"Patient {request.patient_id} full history",
            output_text=json.dumps(summary.model_dump()),
            model=settings.AZURE_OPENAI_DEPLOYMENT,
            provider="azure_openai",
            user_id=request.user_id,
            patient_id=request.patient_id,
            response_time_ms=timer.elapsed_ms
        )

        # TODO: Cache the result

        return Patient360Response(
            summary=summary,
            generated_at=datetime.utcnow().isoformat(),
            cached=False,
            audit_log_id=audit_id
        )

    except ValueError as e:
        message = str(e)
        if message.startswith("Patient ") and message.endswith(" not found"):
            logger.error(f"Patient not found: {e}")
            raise HTTPException(status_code=404, detail=message)

        logger.error(f"Patient 360 value error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=message)
    except Exception as e:
        logger.error(f"Patient 360 generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
