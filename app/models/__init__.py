"""Models module."""
# Import all models for easier access
from app.models.scribe import (
    DictationRequest,
    DictationResponse,
    StructureRequest,
    StructureResponse,
    StreamChunkRequest,
    StructuredConsultation,
    PatientContextInput
)
from app.models.diagnostic import (
    DiagnosticRequest,
    DiagnosticResponse,
    DiagnosticHypothesis,
    Probability
)
from app.models.rx_guard import (
    RxGuardLocalRequest,
    RxGuardLocalResponse,
    RxGuardAIRequest,
    RxGuardAIResponse,
    RxGuardAlert,
    MedicamentInput,
    AlertSeverity,
    AlertType
)
from app.models.patient_360 import (
    Patient360Request,
    Patient360Response,
    Patient360Summary
)
from app.models.alerts import (
    AlertProcessRequest,
    AlertProcessResponse,
    ProcessedAlert
)

__all__ = [
    # Scribe
    "DictationRequest",
    "DictationResponse",
    "StructureRequest",
    "StructureResponse",
    "StreamChunkRequest",
    "StructuredConsultation",
    "PatientContextInput",
    # Diagnostic
    "DiagnosticRequest",
    "DiagnosticResponse",
    "DiagnosticHypothesis",
    "Probability",
    # Rx Guard
    "RxGuardLocalRequest",
    "RxGuardLocalResponse",
    "RxGuardAIRequest",
    "RxGuardAIResponse",
    "RxGuardAlert",
    "MedicamentInput",
    "AlertSeverity",
    "AlertType",
    # Patient 360
    "Patient360Request",
    "Patient360Response",
    "Patient360Summary",
    # Alerts
    "AlertProcessRequest",
    "AlertProcessResponse",
    "ProcessedAlert",
]
