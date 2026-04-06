"""
Smart Alerts engine - automated alert generation based on rules.
"""
import logging
from typing import List, Dict, Any
from datetime import datetime, timedelta
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alerts import ProcessedAlert

logger = logging.getLogger(__name__)


class SmartAlertsEngine:
    """
    Automated alerts engine for operational and clinical warnings.
    Runs via cron to check for alert conditions.
    """

    async def process_alerts(
        self,
        db: AsyncSession,
        cabinet_id: str | None = None
    ) -> tuple[int, List[ProcessedAlert], int]:
        """
        Process all alert rules for a cabinet (or all cabinets).

        Args:
            db: Database session
            cabinet_id: Optional cabinet ID (None = process all cabinets)

        Returns:
            Tuple of (processed_count, new_alerts, skipped_duplicates)
        """
        logger.info(f"Processing alerts for cabinet: {cabinet_id or 'ALL'}")

        new_alerts = []
        skipped = 0

        # Rule 1: Appointment no-shows
        no_show_alerts = await self._check_appointment_no_shows(db, cabinet_id)
        new_alerts.extend(no_show_alerts)

        # Rule 2: Overdue follow-ups
        overdue_alerts = await self._check_overdue_follow_ups(db, cabinet_id)
        new_alerts.extend(overdue_alerts)

        # Rule 3: Missing constantes for protocol patients
        missing_constantes_alerts = await self._check_missing_constantes(db, cabinet_id)
        new_alerts.extend(missing_constantes_alerts)

        # Rule 4: Unread Rx Guard red alerts
        rx_alerts = await self._check_unread_rx_alerts(db, cabinet_id)
        new_alerts.extend(rx_alerts)

        # Deduplicate - don't create alerts that already exist and are active
        deduplicated_alerts = []
        for alert in new_alerts:
            if not await self._alert_exists(db, alert):
                await self._create_alert(db, alert)
                deduplicated_alerts.append(alert)
            else:
                skipped += 1

        await db.commit()

        logger.info(f"Processed {len(deduplicated_alerts)} new alerts, skipped {skipped} duplicates")
        return len(deduplicated_alerts), deduplicated_alerts, skipped

    async def _check_appointment_no_shows(
        self,
        db: AsyncSession,
        cabinet_id: str | None
    ) -> List[ProcessedAlert]:
        """Check for appointments that were missed (no-show)."""
        # Find appointments where date has passed, status still PREVU
        query = text("""
            SELECT rv.id, rv."cabinetId", rv."patientId", rv.date, p.nom, p.prenom
            FROM rendez_vous rv
            JOIN patients p ON rv."patientId" = p.id
            WHERE rv.statut = 'PREVU'
              AND rv.date < NOW() - INTERVAL '2 hours'
              AND (:cabinet_id IS NULL OR rv."cabinetId" = :cabinet_id)
            LIMIT 50
        """)

        result = await db.execute(query, {"cabinet_id": cabinet_id})
        rows = result.mappings().fetchall()

        alerts = []
        for row in rows:
            alerts.append(ProcessedAlert(
                alert_id=f"no-show-{row['id']}",
                type="OPERATIONAL",
                severity="WARNING",
                title=f"Patient absent : {row['nom']} {row['prenom']}",
                patient_id=row['patientId']
            ))

        return alerts

    async def _check_overdue_follow_ups(
        self,
        db: AsyncSession,
        cabinet_id: str | None
    ) -> List[ProcessedAlert]:
        """Check for consultations with overdue follow-up plans."""
        # Find consultations with a follow-up plan > 30 days ago, no new appointment
        query = text("""
            SELECT c.id, c."cabinetId", c."patientId", c.date, c.plan,
                   p.nom, p.prenom
            FROM consultations c
            JOIN patients p ON c."patientId" = p.id
            WHERE c.plan IS NOT NULL
              AND c.plan != ''
              AND c.date < NOW() - INTERVAL '30 days'
              AND c.statut = 'SIGNE'
              AND (:cabinet_id IS NULL OR c."cabinetId" = :cabinet_id)
              AND NOT EXISTS (
                  SELECT 1 FROM rendez_vous rv
                  WHERE rv."patientId" = c."patientId"
                    AND rv.date > c.date
              )
            LIMIT 50
        """)

        result = await db.execute(query, {"cabinet_id": cabinet_id})
        rows = result.mappings().fetchall()

        alerts = []
        for row in rows:
            alerts.append(ProcessedAlert(
                alert_id=f"overdue-followup-{row['id']}",
                type="CLINICAL",
                severity="INFO",
                title=f"Suivi en retard : {row['nom']} {row['prenom']}",
                patient_id=row['patientId']
            ))

        return alerts

    async def _check_missing_constantes(
        self,
        db: AsyncSession,
        cabinet_id: str | None
    ) -> List[ProcessedAlert]:
        """Check for protocol patients missing recent vital signs."""
        # Find patients with active HTA/diabetes protocols, no BP/glucose in 30 days
        query = text("""
            SELECT DISTINCT p.id, p."cabinetId", p.nom, p.prenom, pr.nom as protocol_nom
            FROM patients p
            JOIN patient_protocols pp ON pp."patientId" = p.id
            JOIN protocols pr ON pp."protocolId" = pr.id
            WHERE pp.actif = true
              AND pr.pathologie IN ('HTA', 'Diabète', 'Diabète type 2')
              AND (:cabinet_id IS NULL OR p."cabinetId" = :cabinet_id)
              AND NOT EXISTS (
                  SELECT 1 FROM mesures_patient mp
                  WHERE mp."patientId" = p.id
                    AND mp.date > NOW() - INTERVAL '30 days'
                    AND mp.type IN ('TA_SYS', 'TA_DIA', 'GLYCEMIE', 'HBA1C')
              )
            LIMIT 50
        """)

        result = await db.execute(query, {"cabinet_id": cabinet_id})
        rows = result.mappings().fetchall()

        alerts = []
        for row in rows:
            alerts.append(ProcessedAlert(
                alert_id=f"missing-constantes-{row['id']}",
                type="CLINICAL",
                severity="WARNING",
                title=f"Constantes à contrôler : {row['nom']} {row['prenom']} ({row['protocol_nom']})",
                patient_id=row['id']
            ))

        return alerts

    async def _check_unread_rx_alerts(
        self,
        db: AsyncSession,
        cabinet_id: str | None
    ) -> List[ProcessedAlert]:
        """Check for signed prescriptions with unacknowledged RED alerts."""
        # Find ordonnances signed with rxGuardAlerts containing RED severity
        query = text("""
            SELECT o.id, o."cabinetId", o."patientId", o."rxGuardAlerts",
                   p.nom, p.prenom
            FROM ordonnances o
            JOIN patients p ON o."patientId" = p.id
            WHERE o.statut = 'SIGNEE'
              AND o."rxGuardAlerts" IS NOT NULL
              AND o."rxGuardAlerts"::text LIKE '%RED%'
              AND (:cabinet_id IS NULL OR o."cabinetId" = :cabinet_id)
              AND o."signeLe" > NOW() - INTERVAL '7 days'
            LIMIT 50
        """)

        result = await db.execute(query, {"cabinet_id": cabinet_id})
        rows = result.mappings().fetchall()

        alerts = []
        for row in rows:
            alerts.append(ProcessedAlert(
                alert_id=f"rx-red-alert-{row['id']}",
                type="CLINICAL",
                severity="CRITICAL",
                title=f"Ordonnance avec alerte critique : {row['nom']} {row['prenom']}",
                patient_id=row['patientId']
            ))

        return alerts

    async def _alert_exists(
        self,
        db: AsyncSession,
        alert: ProcessedAlert
    ) -> bool:
        """Check if an alert with the same content already exists and is active."""
        query = text("""
            SELECT COUNT(*) as count
            FROM alerts
            WHERE title = :title
              AND status = 'ACTIVE'
              AND "patientId" = :patient_id
        """)

        result = await db.execute(query, {
            "title": alert.title,
            "patient_id": alert.patient_id
        })
        count = result.scalar()
        return count > 0

    async def _create_alert(
        self,
        db: AsyncSession,
        alert: ProcessedAlert
    ) -> None:
        """Create a new alert in the database."""
        # Extract cabinetId from the alert (need to query or pass it)
        # For now, we'll need to add cabinet_id to ProcessedAlert or fetch it
        # Let's fetch it from patient
        cabinet_query = text("""
            SELECT "cabinetId" FROM patients WHERE id = :patient_id
        """)
        result = await db.execute(cabinet_query, {"patient_id": alert.patient_id})
        cabinet_id = result.scalar()

        if not cabinet_id:
            logger.warning(f"Cannot create alert: patient {alert.patient_id} not found")
            return

        insert_query = text("""
            INSERT INTO alerts (
                "cabinetId", "patientId", type, severity, title,
                description, status, "createdAt"
            )
            VALUES (
                :cabinet_id, :patient_id, :type::\"AlertType\", :severity::\"AlertSeverity\",
                :title, :description, 'ACTIVE', NOW()
            )
        """)

        await db.execute(insert_query, {
            "cabinet_id": cabinet_id,
            "patient_id": alert.patient_id,
            "type": alert.type,
            "severity": alert.severity,
            "title": alert.title,
            "description": alert.title  # Can be enhanced
        })


# Global instance
alerts_engine = SmartAlertsEngine()
