"""
Pydantic models for Patient 360 endpoints.
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class Patient360Request(BaseModel):
    """Request for Patient 360 summary."""
    patient_id: str
    cabinet_id: str
    user_id: Optional[str] = None
    force_regenerate: bool = Field(False, description="Force regeneration even if cached")


class Patient360Summary(BaseModel):
    """AI-generated patient summary."""
    etat_general: str = Field(..., description="General patient overview")
    pathologies_actives: List[str] = Field(default_factory=list, description="Active conditions")
    traitements_principaux: List[str] = Field(default_factory=list, description="Main treatments")
    points_vigilance: List[str] = Field(default_factory=list, description="Points of attention")
    recommandations: List[str] = Field(default_factory=list, description="Recommendations")


class Patient360Response(BaseModel):
    """Response from Patient 360 endpoint."""
    summary: Patient360Summary
    generated_at: str = Field(..., description="ISO timestamp of generation")
    cached: bool = Field(..., description="Was this from cache?")
    audit_log_id: Optional[str] = None
