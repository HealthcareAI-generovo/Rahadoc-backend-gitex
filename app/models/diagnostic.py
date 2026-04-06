"""
Pydantic models for Clinical Copilot endpoints.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class Probability(str, Enum):
    """Diagnostic probability levels."""
    HAUTE = "HAUTE"
    MOYENNE = "MOYENNE"
    FAIBLE = "FAIBLE"


class DiagnosticHypothesis(BaseModel):
    """Single diagnostic hypothesis."""
    name: str = Field(..., description="Diagnostic name")
    probability: Probability = Field(..., description="Likelihood")
    arguments_for: List[str] = Field(default_factory=list, description="Supporting evidence")
    arguments_against: List[str] = Field(default_factory=list, description="Counter-arguments")
    tests: List[str] = Field(default_factory=list, description="Confirmatory tests")


class DiagnosticRequest(BaseModel):
    """Request for diagnostic assistance."""
    consultation_id: str
    patient_id: str
    cabinet_id: str
    user_id: Optional[str] = None


class DiagnosticResponse(BaseModel):
    """Diagnostic AI response."""
    hypotheses: List[DiagnosticHypothesis] = Field(..., description="Ranked diagnostic hypotheses")
    red_flags: List[str] = Field(default_factory=list, description="Urgent warning signs")
    suggested_exams: List[str] = Field(default_factory=list, description="Recommended exams")
    audit_log_id: Optional[str] = None
