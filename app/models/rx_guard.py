"""
Pydantic models for Rx Guard endpoints.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    RED = "RED"       # Blocks signature
    YELLOW = "YELLOW" # Warning
    GREEN = "GREEN"   # Info


class AlertType(str, Enum):
    """Alert types."""
    ALLERGY = "ALLERGY"
    DUPLICATE = "DUPLICATE"
    CONTRAINDICATION = "CONTRAINDICATION"
    INTERACTION = "INTERACTION"
    POSOLOGY = "POSOLOGY"
    DUPLICATION = "DUPLICATION"
    GENERIC_AVAILABLE = "GENERIC_AVAILABLE"


class MedicamentInput(BaseModel):
    """Single medication input."""
    medicament: str
    dci: Optional[str] = None
    dosage: Optional[str] = None
    forme: Optional[str] = None
    posologie: Optional[str] = None
    duree: Optional[str] = None
    classe: Optional[str] = None


class RxGuardAlert(BaseModel):
    """Rx Guard alert."""
    severity: AlertSeverity
    type: AlertType
    medication: str
    description: str
    recommendation: str
    alternative: Optional[str] = None


class RxGuardLocalRequest(BaseModel):
    """Request for local (Layer 1+2) Rx Guard checks."""
    patient_id: str
    cabinet_id: str
    medicament: MedicamentInput
    current_lines: List[MedicamentInput] = Field(default_factory=list)


class RxGuardLocalResponse(BaseModel):
    """Response from local Rx Guard."""
    alerts: List[RxGuardAlert] = Field(default_factory=list)


class RxGuardAIRequest(BaseModel):
    """Request for AI-powered (Layer 3) Rx Guard."""
    patient_id: str
    cabinet_id: str
    ordonnance_lines: List[MedicamentInput]
    user_id: Optional[str] = None


class RxGuardAIResponse(BaseModel):
    """Response from AI Rx Guard."""
    alerts: List[RxGuardAlert] = Field(default_factory=list)
    safe_to_sign: bool = Field(..., description="Can the prescription be signed?")
    audit_log_id: Optional[str] = None
