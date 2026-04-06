"""
Pydantic models for Smart Alerts endpoints.
"""
from pydantic import BaseModel, Field
from typing import List, Optional


class AlertProcessRequest(BaseModel):
    """Request to process alerts (cron endpoint)."""
    cabinet_id: Optional[str] = Field(None, description="Process for specific cabinet (or all if None)")


class ProcessedAlert(BaseModel):
    """Single processed alert result."""
    alert_id: str
    type: str
    severity: str
    title: str
    patient_id: Optional[str] = None


class AlertProcessResponse(BaseModel):
    """Response from alert processing."""
    processed_count: int
    new_alerts: List[ProcessedAlert] = Field(default_factory=list)
    skipped_duplicates: int = Field(0)
