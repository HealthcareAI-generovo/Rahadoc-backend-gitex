"""
Lab Results Explainer API endpoints.

POST /api/v1/lab/analyze   — receive pre-uploaded file bytes, run OCR + AI, return analysis
GET  /api/v1/lab/{id}      — return stored analysis by lab_result_id
"""
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
import logging
import json
from datetime import datetime

from app.dependencies import InternalAuth, DbSession
from app.services.lab_ocr import extract_text, estimate_confidence_label
from app.services.lab_analysis import lab_analysis_service
from app.services.audit import audit_logger, AICallTimer
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/jpg",
    "image/png",
}
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB


class LabAnalyzeRequest(BaseModel):
    lab_result_id: str
    patient_id: str
    cabinet_id: str
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    language: str = "FR"
    previous_lab_result_id: Optional[str] = None
    previous_key_findings: Optional[list] = None  # serialized previous findings for comparison


@router.post("/analyze")
async def analyze_lab_result(
    _: InternalAuth,
    db: DbSession,
    file: UploadFile = File(...),
    request_json: str = Form(...),
):
    """
    Receive a lab result document, run OCR, analyze with AI.

    Accepts:
        - file: PDF or image upload
        - request_json: JSON string with LabAnalyzeRequest fields
    """
    # Parse request metadata
    try:
        req_data = json.loads(request_json)
        request = LabAnalyzeRequest(**req_data)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Invalid request_json: {e}")

    # Validate content type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {content_type}. Allowed: PDF, JPEG, PNG"
        )

    # Read file
    file_bytes = await file.read()
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 10 MB)")

    # OCR extraction
    logger.info(f"Starting OCR for lab result {request.lab_result_id}, type={content_type}")
    extracted_text, ocr_confidence = extract_text(file_bytes, content_type)

    if not extracted_text:
        logger.warning(f"OCR failed for lab result {request.lab_result_id}")
        return {
            "lab_result_id": request.lab_result_id,
            "status": "FAILED",
            "error_message": "ocr_failed",
            "ocr_confidence": 0.0,
        }

    confidence_label = estimate_confidence_label(ocr_confidence)
    logger.info(f"OCR done: {len(extracted_text)} chars, confidence={confidence_label}")

    # AI analysis
    try:
        with AICallTimer() as timer:
            analysis = await lab_analysis_service.analyze(
                lab_result_id=request.lab_result_id,
                extracted_text=extracted_text,
                patient_age=request.patient_age,
                patient_gender=request.patient_gender,
                language=request.language,
                ocr_confidence=ocr_confidence,
                previous_findings=request.previous_key_findings,
            )
    except Exception as e:
        logger.error(f"AI analysis failed: {e}", exc_info=True)
        return {
            "lab_result_id": request.lab_result_id,
            "status": "FAILED",
            "error_message": "ai_analysis_failed",
            "ocr_confidence": ocr_confidence,
        }

    # Audit log
    await audit_logger.log_ai_call(
        db=db,
        cabinet_id=request.cabinet_id,
        action_type="LAB_EXPLAINER",
        input_text=f"Lab result OCR ({len(extracted_text)} chars)",
        output_text=json.dumps({
            "summary": analysis.summary,
            "findings_count": len(analysis.key_findings or []),
            "confidence": analysis.confidence,
        }),
        model=settings.AZURE_OPENAI_DEPLOYMENT,
        provider="azure_openai",
        patient_id=request.patient_id,
        response_time_ms=timer.elapsed_ms,
    )

    return {
        **analysis.model_dump(),
        "extracted_text": extracted_text,
        "ocr_confidence": ocr_confidence,
    }
