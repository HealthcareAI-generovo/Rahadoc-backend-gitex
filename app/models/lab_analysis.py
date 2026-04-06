"""
Pydantic models for Lab Results Explainer.
"""
from pydantic import BaseModel
from typing import Optional, List
from enum import Enum


class AnalysisLanguage(str, Enum):
    FR = "FR"
    EN = "EN"
    AR = "AR"


class LabAnalysisRequest(BaseModel):
    lab_result_id: str
    patient_id: str
    cabinet_id: str
    patient_age: Optional[int] = None
    patient_gender: Optional[str] = None
    language: AnalysisLanguage = AnalysisLanguage.FR
    previous_lab_result_id: Optional[str] = None


class KeyFinding(BaseModel):
    name: str
    value: str
    unit: Optional[str] = None
    reference_range: Optional[str] = None
    status: str  # "normal" | "moderate" | "attention"


class ExplanationItem(BaseModel):
    marker: str
    simple_explanation: str
    possible_causes: List[str]


class ComparisonNote(BaseModel):
    marker: str
    change: str
    direction: str  # "up" | "down" | "stable"


class LabAnalysisResponse(BaseModel):
    lab_result_id: str
    status: str
    summary: Optional[str] = None
    key_findings: Optional[List[KeyFinding]] = None
    explanation: Optional[List[ExplanationItem]] = None
    recommendations: Optional[List[str]] = None
    confidence: Optional[str] = None  # "HIGH" | "MEDIUM" | "LOW"
    disclaimer: Optional[str] = None
    comparison_notes: Optional[List[ComparisonNote]] = None
    error_message: Optional[str] = None
    analyzed_at: Optional[str] = None
