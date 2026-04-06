"""
Rx Guard API endpoints.
"""
from fastapi import APIRouter, HTTPException
import logging
import json

from app.dependencies import InternalAuth, DbSession
from app.models.rx_guard import (
    RxGuardLocalRequest,
    RxGuardLocalResponse,
    RxGuardAIRequest,
    RxGuardAIResponse
)
from app.services.rx_guard_local import rx_guard_local
from app.services.rx_guard_ai import rx_guard_ai_service
from app.services.audit import audit_logger, AICallTimer
from app.db.queries import get_patient_context
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/local", response_model=RxGuardLocalResponse)
async def check_local_safety(
    _: InternalAuth,
    db: DbSession,
    request: RxGuardLocalRequest
):
    """
    Rx Guard Layer 1 + 2: Local safety checks (allergies, duplicates, contraindications).

    This endpoint is fast (<50ms) and doesn't use AI.
    """
    try:
        logger.info(f"Local Rx Guard check for patient {request.patient_id}")

        # Fetch patient data
        patient_ctx = await get_patient_context(db, request.patient_id, request.cabinet_id)
        patient_data = patient_ctx["patient"]

        all_alerts = []

        # Layer 1: Allergies
        allergy_alerts = rx_guard_local.check_allergies(
            patient_allergies=patient_data.get("allergies", ""),
            medicament=request.medicament
        )
        all_alerts.extend(allergy_alerts)

        # Layer 1: Duplicates
        duplicate_alerts = rx_guard_local.check_duplicates(
            current_lines=request.current_lines,
            new_medicament=request.medicament
        )
        all_alerts.extend(duplicate_alerts)

        # Layer 2: Contraindications
        contraindication_alerts = rx_guard_local.check_contraindications(
            patient_data=patient_data,
            medicament=request.medicament
        )
        all_alerts.extend(contraindication_alerts)

        logger.info(f"Local check complete: {len(all_alerts)} alerts")

        return RxGuardLocalResponse(alerts=all_alerts)

    except ValueError as e:
        logger.error(f"Patient not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Local Rx Guard error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ai", response_model=RxGuardAIResponse)
async def check_ai_safety(
    _: InternalAuth,
    db: DbSession,
    request: RxGuardAIRequest
):
    """
    Rx Guard Layer 3: AI-powered safety check for entire prescription.

    Checks interactions, posology, therapeutic overlaps, and suggests generics.
    """
    try:
        logger.info(f"AI Rx Guard check for patient {request.patient_id}")

        # Fetch patient data
        patient_ctx = await get_patient_context(db, request.patient_id, request.cabinet_id)
        patient_data = patient_ctx["patient"]

        # Run AI check
        with AICallTimer() as timer:
            alerts, safe_to_sign = await rx_guard_ai_service.check_prescription(
                patient_data=patient_data,
                ordonnance_lines=[line.model_dump() for line in request.ordonnance_lines],
                chronic_treatments=patient_data.get("traitements", "")
            )

        # Log to audit
        audit_id = await audit_logger.log_ai_call(
            db=db,
            cabinet_id=request.cabinet_id,
            action_type="PRESCRIPTION",
            input_text=json.dumps({
                "lines": [line.model_dump() for line in request.ordonnance_lines]
            }),
            output_text=json.dumps({
                "alerts": [alert.model_dump() for alert in alerts],
                "safe_to_sign": safe_to_sign
            }),
            model=settings.AZURE_OPENAI_DEPLOYMENT,
            provider="azure_openai",
            user_id=request.user_id,
            patient_id=request.patient_id,
            response_time_ms=timer.elapsed_ms
        )

        return RxGuardAIResponse(
            alerts=alerts,
            safe_to_sign=safe_to_sign,
            audit_log_id=audit_id
        )

    except ValueError as e:
        logger.error(f"Patient not found: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"AI Rx Guard error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
