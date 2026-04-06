"""
Alert management for epidemiological anomalies.

Handles:
- Storing anomalies in the dedicated epidemiology_alerts table
- Creating clinical alerts visible in the doctor UI (alerts table)
- Sending email notifications to doctors via Resend
"""
import logging
from typing import List

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.epidemiology.schemas import DetectedAnomaly, DetectionSource, AnomalySeverity
from app.epidemiology.aggregation import (
    store_epidemiology_alert,
    check_recent_alert_exists,
    create_cabinet_alert,
    get_cabinets_by_ville,
    get_doctors_by_ville,
)

logger = logging.getLogger(__name__)

# Map our severity to the main alerts table severity enum
_SEVERITY_TO_ALERT = {
    AnomalySeverity.LOW: "INFO",
    AnomalySeverity.MEDIUM: "WARNING",
    AnomalySeverity.HIGH: "CRITICAL",
}

_SOURCE_LABELS = {
    DetectionSource.Z_SCORE: "Analyse statistique (Z-score)",
    DetectionSource.ISOLATION_FOREST: "Machine Learning (Isolation Forest)",
    DetectionSource.COMBINED: "Double détection (statistique + ML)",
}


async def store_anomalies(
    db: AsyncSession,
    anomalies: List[DetectedAnomaly],
) -> int:
    """
    Store detected anomalies in the epidemiology_alerts table.

    Deduplicates: skips if an alert for the same (region, signal)
    was already created in the last 24 hours.

    Returns number of alerts stored.
    """
    stored = 0
    for anomaly in anomalies:
        # Dedup: skip if recent alert exists
        exists = await check_recent_alert_exists(
            db, anomaly.region, anomaly.disease, hours=24
        )
        if exists:
            logger.info(f"Recent alert exists for {anomaly.disease} in {anomaly.region} — skipping storage")
            continue

        await store_epidemiology_alert(
            db=db,
            region=anomaly.region,
            h3_index=anomaly.h3_index,
            signal=anomaly.disease,
            score=anomaly.score,
            source=anomaly.source.value,
            severity=anomaly.severity.value,
            case_count=anomaly.current_count,
            baseline=anomaly.baseline,
            metadata=anomaly.details,
        )
        stored += 1

    logger.info(f"Stored {stored} epidemiology alerts (skipped {len(anomalies) - stored} duplicates)")
    return stored


async def create_doctor_alerts(
    db: AsyncSession,
    anomalies: List[DetectedAnomaly],
) -> int:
    """
    Create clinical alerts in the main alerts table (visible to doctors).

    Creates one alert per cabinet in the affected city.
    Returns total number of alerts created.
    """
    alerts_created = 0

    for anomaly in anomalies:
        source_label = _SOURCE_LABELS.get(anomaly.source, anomaly.source.value)
        severity = _SEVERITY_TO_ALERT.get(anomaly.severity, "WARNING")

        title = (
            f"Alerte épidémio: {anomaly.disease} à {anomaly.region} "
            f"({anomaly.current_count} cas, score={anomaly.score})"
        )

        description = (
            f"Pic inhabituel de {anomaly.disease} détecté à {anomaly.region}. "
            f"{anomaly.current_count} cas cette semaine contre une moyenne de "
            f"{anomaly.baseline} cas/semaine.\n"
            f"Méthode de détection: {source_label}.\n"
            f"Sévérité: {anomaly.severity.value}."
        )

        metadata = {
            "source": "epidemiology",
            "detection_method": anomaly.source.value,
            "disease": anomaly.disease,
            "ville": anomaly.region,
            "h3_index": anomaly.h3_index,
            "case_count": anomaly.current_count,
            "baseline": anomaly.baseline,
            "score": anomaly.score,
            "severity": anomaly.severity.value,
            "week_start": anomaly.week_start,
        }

        cabinet_ids = await get_cabinets_by_ville(db, anomaly.region)

        for cabinet_id in cabinet_ids:
            alert_id = await create_cabinet_alert(
                db=db,
                cabinet_id=cabinet_id,
                title=title,
                description=description,
                severity=severity,
                metadata=metadata,
            )
            if alert_id:
                alerts_created += 1

    logger.info(f"Created {alerts_created} doctor-visible alerts")
    return alerts_created


async def send_email_alerts(
    db: AsyncSession,
    anomalies: List[DetectedAnomaly],
) -> int:
    """
    Send email alerts to doctors in affected areas via Resend.

    Gracefully degrades if Resend is not configured.
    Returns total number of emails sent.
    """
    if not getattr(settings, "RESEND_API_KEY", None):
        logger.warning("RESEND_API_KEY not configured — skipping email alerts")
        return 0

    try:
        import resend
        resend.api_key = settings.RESEND_API_KEY
    except ImportError:
        logger.warning("resend package not installed — skipping email alerts")
        return 0

    emails_sent = 0

    for anomaly in anomalies:
        try:
            doctors = await get_doctors_by_ville(db, anomaly.region)
            if not doctors:
                continue

            for doctor in doctors:
                if not doctor.get("email"):
                    continue

                sent = _send_single_email(resend, doctor, anomaly)
                if sent:
                    emails_sent += 1

        except Exception as e:
            logger.error(
                f"Failed to send alerts for {anomaly.disease} in {anomaly.region}: {e}",
                exc_info=True
            )

    logger.info(f"Sent {emails_sent} epidemic alert emails")
    return emails_sent


def _send_single_email(resend_module, doctor: dict, anomaly: DetectedAnomaly) -> bool:
    """Send a single alert email. Returns True if sent."""
    severity_map = {
        AnomalySeverity.HIGH: ("CRITIQUE", "#DC2626"),
        AnomalySeverity.MEDIUM: ("ATTENTION", "#D97706"),
        AnomalySeverity.LOW: ("INFO", "#2563EB"),
    }
    severity_label, severity_color = severity_map.get(
        anomaly.severity, ("INFO", "#2563EB")
    )

    source_label = _SOURCE_LABELS.get(anomaly.source, anomaly.source.value)

    subject = (
        f"[RahaDoc] Alerte épidémiologique: "
        f"{anomaly.disease} à {anomaly.region}"
    )

    html_body = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
        <div style="background: {severity_color}; color: white; padding: 16px 24px; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0; font-size: 18px;">
                {severity_label} — Alerte Épidémiologique
            </h2>
        </div>
        <div style="border: 1px solid #E5E7EB; border-top: none; padding: 24px; border-radius: 0 0 8px 8px;">
            <p style="margin-top: 0;">
                Bonjour Dr. {doctor.get('nom', '')},
            </p>
            <p>
                Un pic inhabituel de <strong>{anomaly.disease}</strong> a été détecté
                dans votre zone (<strong>{anomaly.region}</strong>).
            </p>
            <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
                <tr style="border-bottom: 1px solid #E5E7EB;">
                    <td style="padding: 8px 0; color: #6B7280;">Maladie</td>
                    <td style="padding: 8px 0; font-weight: bold;">{anomaly.disease}</td>
                </tr>
                <tr style="border-bottom: 1px solid #E5E7EB;">
                    <td style="padding: 8px 0; color: #6B7280;">Zone</td>
                    <td style="padding: 8px 0; font-weight: bold;">{anomaly.region}</td>
                </tr>
                <tr style="border-bottom: 1px solid #E5E7EB;">
                    <td style="padding: 8px 0; color: #6B7280;">Cas cette semaine</td>
                    <td style="padding: 8px 0; font-weight: bold; color: {severity_color};">{anomaly.current_count}</td>
                </tr>
                <tr style="border-bottom: 1px solid #E5E7EB;">
                    <td style="padding: 8px 0; color: #6B7280;">Moyenne historique</td>
                    <td style="padding: 8px 0;">{anomaly.baseline} cas/semaine</td>
                </tr>
                <tr style="border-bottom: 1px solid #E5E7EB;">
                    <td style="padding: 8px 0; color: #6B7280;">Score</td>
                    <td style="padding: 8px 0; font-weight: bold;">{anomaly.score}</td>
                </tr>
                <tr style="border-bottom: 1px solid #E5E7EB;">
                    <td style="padding: 8px 0; color: #6B7280;">Détection</td>
                    <td style="padding: 8px 0;">{source_label}</td>
                </tr>
                <tr>
                    <td style="padding: 8px 0; color: #6B7280;">Sévérité</td>
                    <td style="padding: 8px 0; font-weight: bold; color: {severity_color};">{severity_label}</td>
                </tr>
            </table>
            <p style="color: #6B7280; font-size: 14px;">
                Veuillez surveiller vos patients et signaler tout cas similaire.
                Cette alerte a été générée automatiquement par le système de
                surveillance épidémiologique de RahaDoc.
            </p>
        </div>
    </div>
    """

    try:
        resend_module.Emails.send({
            "from": getattr(settings, "ALERT_EMAIL_FROM", "RahaDoc <alerts@rahadoc.ma>"),
            "to": doctor["email"],
            "subject": subject,
            "html": html_body,
        })
        logger.info(f"Sent alert to {doctor['email']} ({anomaly.disease} in {anomaly.region})")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {doctor['email']}: {e}", exc_info=True)
        return False
