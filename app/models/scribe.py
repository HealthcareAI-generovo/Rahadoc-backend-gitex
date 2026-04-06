"""
Pydantic models for MedScribe endpoints.
"""
from pydantic import BaseModel, Field
from typing import Optional


class PatientContextInput(BaseModel):
    """Patient context for AI processing."""
    antecedents: Optional[str] = None
    allergies: Optional[str] = None
    traitements: Optional[str] = None


class DictationRequest(BaseModel):
    """Request for post-dictation structuring."""
    consultation_id: str = Field(..., description="Consultation ID")
    cabinet_id: str = Field(..., description="Cabinet ID (for security)")
    user_id: Optional[str] = Field(None, description="User performing dictation")
    patient_id: str = Field(..., description="Patient ID")
    patient_context: PatientContextInput = Field(..., description="Patient medical context")
    language: Optional[str] = Field(None, description="Expected language (fr, ar, etc.)")


class StructuredConsultation(BaseModel):
    """Structured consultation output from AI."""
    motif: Optional[str] = None
    histoireMaladie: Optional[str] = None
    examenClinique: Optional[str] = None
    diagnostic: Optional[str] = None
    plan: Optional[str] = None


class DictationResponse(BaseModel):
    """Response from dictation endpoint."""
    transcript: str = Field(..., description="Raw transcription text")
    transcription_lang: str = Field(..., description="Detected language")
    structured: StructuredConsultation = Field(..., description="Structured consultation data")
    audit_log_id: Optional[str] = None


class StructureRequest(BaseModel):
    """Request for structuring an existing transcript without audio upload."""
    consultation_id: str = Field(..., description="Consultation ID")
    cabinet_id: str = Field(..., description="Cabinet ID (for security)")
    user_id: Optional[str] = Field(None, description="User performing structuring")
    patient_id: str = Field(..., description="Patient ID")
    transcript: str = Field(..., description="Raw transcript text")
    patient_context: PatientContextInput = Field(..., description="Patient medical context")


class StructureResponse(BaseModel):
    """Response from structure-only endpoint."""
    structured: StructuredConsultation = Field(..., description="Structured consultation data")
    audit_log_id: Optional[str] = None


class StreamChunkRequest(BaseModel):
    """Request for ambient mode streaming."""
    session_id: str = Field(..., description="Streaming session ID")
    consultation_id: str = Field(..., description="Consultation ID")
    cabinet_id: str = Field(..., description="Cabinet ID")
    user_id: Optional[str] = None
    patient_id: str = Field(..., description="Patient ID")
    patient_context: PatientContextInput
    is_last: bool = Field(False, description="Is this the final chunk?")
    language: Optional[str] = None
