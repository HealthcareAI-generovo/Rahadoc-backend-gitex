"""
Epidemiology surveillance service — main orchestrator.

Coordinates the full scan pipeline:
1. Fetch aggregated consultation data
2. Run detection layers (z-score, Isolation Forest, or both)
3. Merge and deduplicate results
4. Store anomalies in dedicated table
5. Create doctor-visible alerts
6. Send email notifications
"""
import logging
import time
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.epidemiology.schemas import (
    ScanConfig,
    EpidemiologyScanResponse,
)
from app.epidemiology.aggregation import get_weekly_disease_counts
from app.epidemiology.detection import (
    group_rows_by_region_disease,
    detect_zscore,
    detect_isolation_forest,
    merge_detection_results,
)
from app.epidemiology.alerts import (
    store_anomalies,
    create_doctor_alerts,
    send_email_alerts,
)

logger = logging.getLogger(__name__)


class EpidemiologyService:
    """
    Main orchestrator for epidemiological surveillance scans.

    Usage:
        result = await epidemiology_service.run_scan(db)
        result = await epidemiology_service.run_scan(db, config=ScanConfig(enable_ml=False))
    """

    async def run_scan(
        self,
        db: AsyncSession,
        config: ScanConfig | None = None,
    ) -> EpidemiologyScanResponse:
        """
        Execute a full epidemiology scan pipeline.

        Args:
            db: Database session
            config: Scan configuration (uses defaults if None)

        Returns:
            EpidemiologyScanResponse with all results and metrics
        """
        if config is None:
            config = ScanConfig()

        start_time = time.time()
        logger.info(
            f"=== Epidemiology scan started === "
            f"(zscore={config.enable_zscore}, ml={config.enable_ml}, "
            f"weeks={config.weeks_back})"
        )

        # ── Step 1: Fetch data ──
        rows = await get_weekly_disease_counts(db, weeks_back=config.weeks_back)
        records_processed = len(rows)

        if not rows:
            logger.info("No consultation data found — scan complete (empty)")
            return EpidemiologyScanResponse(
                anomalies_found=0,
                alerts_created=0,
                emails_sent=0,
                records_processed=0,
                scan_timestamp=datetime.utcnow().isoformat(),
                config_used=config,
            )

        # ── Step 2: Group by region + disease ──
        grouped = group_rows_by_region_disease(rows)
        logger.info(f"Grouped into {len(grouped)} (region, disease) pairs")

        # ── Step 3: Run detection layers ──
        zscore_anomalies = []
        ml_anomalies = []

        if config.enable_zscore:
            zscore_anomalies = detect_zscore(grouped, config)

        if config.enable_ml:
            ml_anomalies = detect_isolation_forest(grouped, config)

        # ── Step 4: Merge results ──
        if config.enable_zscore and config.enable_ml:
            all_anomalies = merge_detection_results(zscore_anomalies, ml_anomalies)
        elif config.enable_zscore:
            all_anomalies = zscore_anomalies
        elif config.enable_ml:
            all_anomalies = ml_anomalies
        else:
            all_anomalies = []

        # Count combined (detected by both)
        combined_count = sum(1 for a in all_anomalies if a.source.value == "COMBINED")

        logger.info(
            f"Detection complete: {len(all_anomalies)} total anomalies "
            f"({len(zscore_anomalies)} z-score, {len(ml_anomalies)} ML, "
            f"{combined_count} combined)"
        )

        # ── Step 5: Store anomalies ──
        alerts_stored = 0
        if all_anomalies:
            alerts_stored = await store_anomalies(db, all_anomalies)

        # ── Step 6: Create doctor alerts ──
        alerts_created = 0
        if all_anomalies:
            alerts_created = await create_doctor_alerts(db, all_anomalies)

        await db.commit()

        # ── Step 7: Send emails ──
        emails_sent = 0
        if all_anomalies:
            emails_sent = await send_email_alerts(db, all_anomalies)

        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.info(
            f"=== Epidemiology scan complete in {elapsed_ms}ms === "
            f"records={records_processed}, anomalies={len(all_anomalies)}, "
            f"alerts_stored={alerts_stored}, doctor_alerts={alerts_created}, "
            f"emails={emails_sent}"
        )

        return EpidemiologyScanResponse(
            anomalies_found=len(all_anomalies),
            alerts_created=alerts_created,
            emails_sent=emails_sent,
            records_processed=records_processed,
            zscore_anomalies=len(zscore_anomalies),
            ml_anomalies=len(ml_anomalies),
            combined_anomalies=combined_count,
            anomalies=all_anomalies,
            scan_timestamp=datetime.utcnow().isoformat(),
            config_used=config,
        )


# Global instance
epidemiology_service = EpidemiologyService()
