"""
Epidemiology surveillance API endpoints.
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import logging

from app.dependencies import CronAuth, DbSession, InternalAuth
from app.epidemiology.schemas import (
    EpidemiologyScanRequest,
    EpidemiologyScanResponse,
    HeatmapPoint,
    ScanConfig,
    SimulationStartResponse,
    SimulationStopResponse,
    SimulationStatus,
)
from app.epidemiology.service import epidemiology_service
from app.epidemiology.aggregation import get_heatmap_data
from app.epidemiology import simulation as sim_engine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/scan", response_model=EpidemiologyScanResponse)
async def scan_epidemiology(
    _: CronAuth,
    db: DbSession,
    request: EpidemiologyScanRequest | None = None,
):
    """
    Run an epidemiological anomaly scan.

    Multi-layer detection pipeline:
    - Layer 1: Z-score statistical analysis
    - Layer 2: Isolation Forest machine learning
    - Geospatial: H3 hexagonal grouping (when coordinates available)

    Protected by X-Cron-Secret header.
    Callable by Railway cron scheduler (daily) or manually.

    Optional request body to override scan configuration:
    ```json
    {
        "config": {
            "enable_zscore": true,
            "enable_ml": true,
            "weeks_back": 8,
            "zscore_warning": 2.0,
            "zscore_critical": 3.0,
            "ml_contamination": 0.05,
            "ml_min_samples": 30
        }
    }
    ```
    """
    try:
        config = request.config if request and request.config else ScanConfig()

        result = await epidemiology_service.run_scan(db=db, config=config)

        return result

    except Exception as e:
        logger.error(f"Epidemiology scan error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/heatmap", response_model=list[HeatmapPoint])
async def get_heatmap(
    _: InternalAuth,
    db: DbSession,
    signal: Optional[str] = Query(None, description="Filter by disease (e.g. 'Grippe')"),
    days: int = Query(30, ge=1, le=365, description="Number of days to look back"),
):
    """
    Return heatmap data points for Morocco map visualization.

    Each point has lat/lng, case intensity, disease signal, and anomaly flag.
    Protected by X-Internal-Secret header (Next.js frontend only).
    """
    try:
        rows = await get_heatmap_data(db=db, signal=signal, days_back=days)
        points = [
            HeatmapPoint(
                lat=row["latitude"],
                lng=row["longitude"],
                intensity=int(row["case_count"]),
                signal=row["disease"],
                ville=row["ville"],
                anomaly=bool(row["is_anomaly"]),
            )
            for row in rows
        ]
        return points
    except Exception as e:
        logger.error(f"Heatmap fetch error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Simulation control endpoints
# All protected by X-Internal-Secret (same as heatmap — Next.js / admins only)
# ---------------------------------------------------------------------------

@router.post("/simulation/start", response_model=SimulationStartResponse)
async def start_simulation(_: InternalAuth):
    """
    Start the background simulation loop.

    Generates synthetic consultation data continuously so the heatmap,
    detection pipeline, and alert system can be exercised without real patients.

    Idempotent — calling while already running returns the current status.
    """
    try:
        result = await sim_engine.start_simulation()
        return result
    except Exception as e:
        logger.error(f"Simulation start error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/simulation/stop", response_model=SimulationStopResponse)
async def stop_simulation(_: InternalAuth):
    """
    Stop the background simulation loop.

    Already-inserted rows remain in the database (marked is_simulation=true).
    Use DELETE /simulation/purge to remove them.

    Idempotent — calling while not running returns the current status.
    """
    try:
        result = await sim_engine.stop_simulation()
        return result
    except Exception as e:
        logger.error(f"Simulation stop error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/simulation/status", response_model=SimulationStatus)
async def simulation_status(_: InternalAuth):
    """
    Return current simulation engine state.

    Includes: running flag, uptime, cycle count, rows inserted,
    which anomaly scenarios have fired, and configuration.
    """
    return sim_engine.get_status()


@router.delete("/simulation/purge")
async def purge_simulation_data(_: InternalAuth, db: DbSession):
    """
    Delete all rows created by the simulation engine (is_simulation=TRUE).

    Does NOT stop the simulation if it is running — stop it first if needed.
    Returns the number of rows deleted per table.
    """
    try:
        from sqlalchemy import text

        # Delete consultations
        result = await db.execute(
            text("DELETE FROM consultations WHERE is_simulation = TRUE")
        )
        cons_deleted = result.rowcount

        await db.commit()
        logger.info(f"[SIM] Purged {cons_deleted} simulation consultation rows.")
        return {"deleted_consultations": cons_deleted}
    except Exception as e:
        logger.error(f"Simulation purge error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
