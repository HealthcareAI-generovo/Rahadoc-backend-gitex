"""
Pydantic models for the epidemiology surveillance module.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum


class DetectionSource(str, Enum):
    Z_SCORE = "Z_SCORE"
    ISOLATION_FOREST = "ISOLATION_FOREST"
    COMBINED = "COMBINED"


class AnomalySeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DetectedAnomaly(BaseModel):
    """A single detected anomaly from any detection layer."""
    region: str = Field(description="City name (human-readable)")
    h3_index: Optional[str] = Field(None, description="H3 hex index if available")
    disease: str = Field(description="Disease category")
    current_count: int
    baseline: float = Field(description="Historical mean")
    score: float = Field(description="Z-score or anomaly score")
    source: DetectionSource
    severity: AnomalySeverity
    week_start: str = Field(description="ISO date of the analysis window start")
    details: dict = Field(default_factory=dict, description="Extra detection details")


class ScanConfig(BaseModel):
    """Configuration for a scan run."""
    enable_zscore: bool = Field(True, description="Enable z-score detection layer")
    enable_ml: bool = Field(True, description="Enable Isolation Forest detection layer")
    weeks_back: int = Field(8, description="Weeks of history to analyze", ge=4, le=52)
    zscore_warning: float = Field(2.0, description="Z-score threshold for WARNING")
    zscore_critical: float = Field(3.0, description="Z-score threshold for CRITICAL")
    ml_contamination: float = Field(0.05, description="Isolation Forest contamination param", ge=0.01, le=0.2)
    ml_min_samples: int = Field(30, description="Minimum samples to run Isolation Forest", ge=10)


class EpidemiologyScanRequest(BaseModel):
    """Request body for the scan endpoint."""
    config: Optional[ScanConfig] = Field(None, description="Override default scan config")


class EpidemiologyScanResponse(BaseModel):
    """Response from the epidemiology scan endpoint."""
    anomalies_found: int
    alerts_created: int
    emails_sent: int
    records_processed: int = Field(0, description="Number of data points analyzed")
    zscore_anomalies: int = Field(0)
    ml_anomalies: int = Field(0)
    combined_anomalies: int = Field(0, description="Detected by both layers (HIGH confidence)")
    anomalies: List[DetectedAnomaly] = Field(default_factory=list)
    scan_timestamp: str
    config_used: ScanConfig = Field(default_factory=ScanConfig)


class HeatmapPoint(BaseModel):
    """A single point for the heatmap visualization."""
    lat: float
    lng: float
    intensity: int = Field(description="Number of cases — drives heat intensity")
    signal: str = Field(description="Disease category")
    ville: str = Field(description="City name")
    anomaly: bool = Field(False, description="True if this region has a detected anomaly")


# Keep backward compat alias for the old model name
EpidemiologyAnomaly = DetectedAnomaly


# ---------------------------------------------------------------------------
# Simulation control schemas
# ---------------------------------------------------------------------------

class SimulationStatus(BaseModel):
    """Current state of the simulation engine."""
    running: bool
    uptime_seconds: float
    cycles_completed: int
    total_rows_inserted: int
    scenario_flu_casablanca_fired: bool
    scenario_food_rabat_fired: bool
    interval_seconds: int
    seed: Optional[int]


class SimulationStartResponse(BaseModel):
    started: bool
    reason: Optional[str] = None
    status: SimulationStatus


class SimulationStopResponse(BaseModel):
    stopped: bool
    reason: Optional[str] = None
    status: SimulationStatus
