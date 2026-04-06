"""
Main API v1 router - mounts all sub-routers.
"""
from fastapi import APIRouter

from app.api.v1 import scribe, diagnostic, rx_guard, patient_360, alerts, epidemiology, lab_analysis

api_router = APIRouter()

# Mount all sub-routers
api_router.include_router(scribe.router, prefix="/scribe", tags=["MedScribe"])
api_router.include_router(diagnostic.router, prefix="/diagnostic", tags=["Clinical Copilot"])
api_router.include_router(rx_guard.router, prefix="/rx-guard", tags=["Rx Guard"])
api_router.include_router(patient_360.router, prefix="/patient-360", tags=["Patient 360"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["Smart Alerts"])
api_router.include_router(epidemiology.router, prefix="/epidemiology", tags=["Epidemiology"])
api_router.include_router(lab_analysis.router, prefix="/lab", tags=["Lab Results Explainer"])
