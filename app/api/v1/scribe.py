"""
MedScribe API endpoints.
"""
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
import logging
import json
from typing import AsyncIterator

from app.dependencies import InternalAuth, DbSession
from app.models.scribe import (
    DictationRequest,
    DictationResponse,
    StructureRequest,
    StructureResponse,
    StreamChunkRequest,
    PatientContextInput,
    StructuredConsultation
)
from app.services.scribe import medscribe_service
from app.services.azure_openai import azure_service
from app.services.audit import audit_logger, AICallTimer
from app.db.queries import get_patient_context
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# In-memory storage for streaming sessions
streaming_sessions: dict[str, dict] = {}


@router.post("/dictation", response_model=DictationResponse)
async def process_dictation(
    _: InternalAuth,
    db: DbSession,
    audio: UploadFile = File(...),
    request_json: str = Form(...)
):
    """
    Process post-dictation audio: transcribe + structure.

    Accepts multipart/form-data with:
    - audio: Audio file (Opus, MP3, WAV, etc.)
    - request_json: JSON string with DictationRequest data
    """
    try:
        # Parse request
        req_data = json.loads(request_json)
        request = DictationRequest(**req_data)

        # Verify cabinet ownership
        patient_ctx = await get_patient_context(db, request.patient_id, request.cabinet_id)

        # Read audio
        audio_bytes = await audio.read()
        audio_filename = audio.filename or "dictation.webm"
        if "." not in audio_filename and audio.content_type:
            if "webm" in audio.content_type:
                audio_filename = f"{audio_filename}.webm"
            elif "wav" in audio.content_type:
                audio_filename = f"{audio_filename}.wav"
            elif "ogg" in audio.content_type or "oga" in audio.content_type:
                audio_filename = f"{audio_filename}.ogg"
            elif "mp3" in audio.content_type or "mpeg" in audio.content_type:
                audio_filename = f"{audio_filename}.mp3"
            elif "mp4" in audio.content_type or "m4a" in audio.content_type:
                audio_filename = f"{audio_filename}.mp4"
            else:
                audio_filename = f"{audio_filename}.webm"
        logger.info(f"Received audio: {len(audio_bytes)} bytes for consultation {request.consultation_id}")

        # Process with timer
        with AICallTimer() as timer:
            transcript, detected_lang, structured = await medscribe_service.process_dictation(
                audio_bytes=audio_bytes,
                patient_context=request.patient_context.model_dump(),
                language=request.language,
                filename=audio_filename,
            )

        # Log to audit
        audit_id = await audit_logger.log_ai_call(
            db=db,
            cabinet_id=request.cabinet_id,
            action_type="SCRIBE",
            input_text=f"Audio dictation ({len(audio_bytes)} bytes)",
            output_text=json.dumps(structured.model_dump()),
            model=settings.AZURE_OPENAI_DEPLOYMENT,
            provider="azure_openai",
            user_id=request.user_id,
            patient_id=request.patient_id,
            response_time_ms=timer.elapsed_ms
        )

        return DictationResponse(
            transcript=transcript,
            transcription_lang=detected_lang,
            structured=structured,
            audit_log_id=audit_id
        )

    except Exception as e:
        logger.error(f"Dictation processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/structure", response_model=StructureResponse)
async def structure_transcript(
    _: InternalAuth,
    db: DbSession,
    request: StructureRequest
):
    """
    Structure an existing transcript without uploading audio.
    """
    try:
        # Verify cabinet ownership
        await get_patient_context(db, request.patient_id, request.cabinet_id)

        with AICallTimer() as timer:
            structured = await medscribe_service._structure_transcript(
                transcript=request.transcript,
                patient_context=request.patient_context.model_dump()
            )

        audit_id = await audit_logger.log_ai_call(
            db=db,
            cabinet_id=request.cabinet_id,
            action_type="SCRIBE",
            input_text=f"Structure-only transcript ({len(request.transcript)} chars)",
            output_text=json.dumps(structured.model_dump()),
            model=settings.AZURE_OPENAI_DEPLOYMENT,
            provider="azure_openai",
            user_id=request.user_id,
            patient_id=request.patient_id,
            response_time_ms=timer.elapsed_ms
        )

        return StructureResponse(
            structured=structured,
            audit_log_id=audit_id
        )

    except Exception as e:
        logger.error(f"Structure-only processing error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/stream")
async def process_stream_chunk(
    _: InternalAuth,
    db: DbSession,
    audio: UploadFile = File(...),
    request_json: str = Form(...)
):
    """
    Process ambient mode streaming chunk.

    Returns SSE stream with progressive transcription and final structuring.
    """
    try:
        # Parse request
        req_data = json.loads(request_json)
        request = StreamChunkRequest(**req_data)

        # Initialize session if new
        if request.session_id not in streaming_sessions:
            streaming_sessions[request.session_id] = {
                "transcript_parts": [],
                "consultation_id": request.consultation_id,
                "cabinet_id": request.cabinet_id,
                "patient_id": request.patient_id,
                "patient_context": request.patient_context.model_dump()
            }

        session = streaming_sessions[request.session_id]

        # Read audio chunk
        audio_bytes = await audio.read()

        # Stream response
        async def generate_events() -> AsyncIterator[str]:
            """Generate SSE events."""
            try:
                # Transcribe chunk
                transcript_chunk = await azure_service.transcribe_audio(
                    audio_file=audio_bytes,
                    language=request.language,
                    filename="chunk.webm"
                )

                # Append to session
                session["transcript_parts"].append(transcript_chunk)

                # Yield partial transcript
                yield f"data: {json.dumps({'transcript': transcript_chunk})}\n\n"

                # If final chunk, run structuring
                if request.is_last:
                    full_transcript = " ".join(session["transcript_parts"])

                    # Structure
                    structured = await medscribe_service._structure_transcript(
                        transcript=full_transcript,
                        patient_context=session["patient_context"]
                    )

                    # Yield structured result
                    yield f"data: {json.dumps({'structured': structured.model_dump()})}\n\n"

                    # Log to audit
                    await audit_logger.log_ai_call(
                        db=db,
                        cabinet_id=request.cabinet_id,
                        action_type="SCRIBE",
                        input_text=f"Ambient mode: {full_transcript[:500]}...",
                        output_text=json.dumps(structured.model_dump()),
                        model=settings.AZURE_OPENAI_DEPLOYMENT,
                        provider="azure_openai",
                        user_id=request.user_id,
                        patient_id=request.patient_id
                    )

                    # Clean up session
                    del streaming_sessions[request.session_id]

                    # Send completion event
                    yield f"data: {json.dumps({'done': True})}\n\n"

            except Exception as e:
                logger.error(f"Stream processing error: {e}", exc_info=True)
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            generate_events(),
            media_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"Stream chunk error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
