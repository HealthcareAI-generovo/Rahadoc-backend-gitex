"""
Clinical Copilot API endpoints.
"""
from fastapi import APIRouter, HTTPException
import logging
import json

from app.dependencies import InternalAuth, DbSession
from app.models.diagnostic import DiagnosticRequest, DiagnosticResponse
from app.services.diagnostic import copilot_service
from app.services.audit import audit_logger, AICallTimer
from app.db.queries import get_consultation_data, get_patient_context
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/hypotheses", response_model=DiagnosticResponse)
async def generate_diagnostic_hypotheses(
    _: InternalAuth,
    db: DbSession,
    request: DiagnosticRequest
):
    """
    Generate diagnostic hypotheses for a consultation.

    Returns ranked hypotheses with supporting evidence and suggested exams.
    """
    try:
        logger.info(f"Generating hypotheses for consultation {request.consultation_id}")

        # Fetch data
        consultation_data = await get_consultation_data(
            db,
            request.consultation_id,
            request.cabinet_id
        )

        patient_context = await get_patient_context(
            db,
            request.patient_id,
            request.cabinet_id
        )

        # Generate hypotheses
        with AICallTimer() as timer:
            response = await copilot_service.generate_hypotheses(
                patient_data=patient_context["patient"],
                consultation_data=consultation_data
            )

        # Log to audit
        audit_id = await audit_logger.log_ai_call(
            db=db,
            cabinet_id=request.cabinet_id,
            action_type="DIAGNOSTIC",
            input_text=json.dumps({
                "motif": consultation_data.get("motif"),
                "histoire": consultation_data.get("histoireMaladie")
            }),
            output_text=json.dumps({
                "hypotheses": [h.model_dump() for h in response.hypotheses],
                "red_flags": response.red_flags
            }),
            model=settings.AZURE_OPENAI_DEPLOYMENT,
            provider="azure_openai",
            user_id=request.user_id,
            patient_id=request.patient_id,
            response_time_ms=timer.elapsed_ms
        )

        response.audit_log_id = audit_id
        return response

    except ValueError as e:
        logger.error(f"Data not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Diagnostic generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
