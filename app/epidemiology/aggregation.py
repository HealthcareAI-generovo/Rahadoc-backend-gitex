"""
SQL aggregation queries for epidemiological surveillance.

Fetches consultation data grouped by region (ville or H3) and disease.
Uses the same raw SQL + text() pattern as app/db/queries.py.
"""
import json
import logging
from typing import List, Dict, Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.epidemiology.keywords import get_keyword_patterns

logger = logging.getLogger(__name__)


def _build_values_clause() -> str:
    """
    Build a SQL VALUES clause from the static disease keyword patterns.

    Keywords are static constants (not user input), so building them
    into the SQL string is safe from injection.
    """
    patterns = get_keyword_patterns()
    rows = []
    for category, pattern in patterns:
        safe_cat = category.replace("'", "''")
        safe_pat = pattern.replace("'", "''")
        rows.append(f"('{safe_cat}', '{safe_pat}')")
    return ",\n        ".join(rows)


# Pre-build at module load time (static data)
_KEYWORD_VALUES = _build_values_clause()


async def get_weekly_disease_counts(
    db: AsyncSession,
    weeks_back: int = 8
) -> List[Dict[str, Any]]:
    """
    Aggregate signed consultation counts per (region, disease, week).

    Returns dicts with keys:
      ville, latitude, longitude, disease, week_start, case_count
    """
    query = text(f"""
        WITH disease_keywords(category, pattern) AS (
            VALUES
                {_KEYWORD_VALUES}
        )
        SELECT
            cab.ville,
            cab.latitude,
            cab.longitude,
            dk.category AS disease,
            DATE_TRUNC('week', c.date)::date AS week_start,
            COUNT(DISTINCT c.id) AS case_count
        FROM consultations c
        JOIN cabinets cab ON c."cabinetId" = cab.id
        JOIN disease_keywords dk ON LOWER(c.diagnostic) LIKE dk.pattern
        WHERE c.statut = 'SIGNE'
          AND c.diagnostic IS NOT NULL
          AND cab.ville IS NOT NULL
          AND c.date >= NOW() - make_interval(weeks => :weeks_back)
        GROUP BY cab.ville, cab.latitude, cab.longitude, dk.category, DATE_TRUNC('week', c.date)
        ORDER BY ville, disease, week_start
    """)

    try:
        result = await db.execute(query, {"weeks_back": weeks_back})
        rows = result.mappings().fetchall()
        count = len(rows)
        logger.info(f"Fetched {count} weekly disease count rows ({weeks_back} weeks)")
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch weekly disease counts: {e}", exc_info=True)
        raise


async def get_doctors_by_ville(
    db: AsyncSession,
    ville: str
) -> List[Dict[str, Any]]:
    """Get all active doctors (MEDECIN) in cabinets in a given city."""
    query = text("""
        SELECT DISTINCT u.id, u.nom, u.prenom, u.email
        FROM users u
        JOIN cabinets cab ON u."cabinetId" = cab.id
        WHERE u.role = 'MEDECIN'
          AND u.actif = true
          AND cab.ville = :ville
    """)

    try:
        result = await db.execute(query, {"ville": ville})
        rows = result.mappings().fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch doctors for ville {ville}: {e}", exc_info=True)
        raise


async def get_cabinets_by_ville(
    db: AsyncSession,
    ville: str
) -> List[str]:
    """Get all cabinet IDs in a given city."""
    query = text("""
        SELECT id FROM cabinets WHERE ville = :ville
    """)

    try:
        result = await db.execute(query, {"ville": ville})
        return [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.error(f"Failed to fetch cabinets for ville {ville}: {e}", exc_info=True)
        raise


async def store_epidemiology_alert(
    db: AsyncSession,
    region: str,
    h3_index: Optional[str],
    signal: str,
    score: float,
    source: str,
    severity: str,
    case_count: int,
    baseline: float,
    metadata: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Store an anomaly in the dedicated epidemiology_alerts table.

    Returns the alert ID.
    """
    # Inline enum casts — source/severity are internal constants, not user input
    safe_source = source.replace("'", "''")
    safe_severity = severity.replace("'", "''")
    query = text(f"""
        INSERT INTO epidemiology_alerts (
            id, region, "h3Index", signal, score, source, severity,
            "caseCount", baseline, metadata, "createdAt"
        )
        VALUES (
            gen_random_uuid()::text, :region, :h3_index, :signal, :score,
            '{safe_source}'::"EpidemiologySource", '{safe_severity}'::"EpidemiologySeverity",
            :case_count, :baseline, CAST(:metadata AS jsonb), NOW()
        )
        RETURNING id
    """)

    try:
        result = await db.execute(query, {
            "region": region,
            "h3_index": h3_index,
            "signal": signal,
            "score": score,
            "case_count": case_count,
            "baseline": baseline,
            "metadata": json.dumps(metadata) if metadata else None,
        })
        alert_id = result.scalar_one()
        return alert_id
    except Exception as e:
        logger.error(f"Failed to store epidemiology alert: {e}", exc_info=True)
        raise


async def check_recent_alert_exists(
    db: AsyncSession,
    region: str,
    signal: str,
    hours: int = 24
) -> bool:
    """Check if an alert for this (region, signal) was created recently."""
    query = text("""
        SELECT COUNT(*) FROM epidemiology_alerts
        WHERE region = :region
          AND signal = :signal
          AND "createdAt" >= NOW() - make_interval(hours => :hours)
    """)

    try:
        result = await db.execute(query, {
            "region": region,
            "signal": signal,
            "hours": hours,
        })
        return result.scalar() > 0
    except Exception as e:
        logger.error(f"Failed to check recent alert: {e}", exc_info=True)
        raise


async def get_heatmap_data(
    db: AsyncSession,
    signal: Optional[str] = None,
    days_back: int = 30,
) -> list[dict]:
    """
    Aggregate case counts for heatmap visualization.

    Returns one row per (ville, disease) with lat/lng and total cases.
    Also joins against epidemiology_alerts to flag anomaly regions.
    """
    signal_filter = "AND dk.category = :signal" if signal else ""

    query = text(f"""
        WITH disease_keywords(category, pattern) AS (
            VALUES
                {_KEYWORD_VALUES}
        ),
        case_counts AS (
            SELECT
                cab.ville,
                cab.latitude,
                cab.longitude,
                dk.category AS disease,
                COUNT(DISTINCT c.id) AS case_count
            FROM consultations c
            JOIN cabinets cab ON c."cabinetId" = cab.id
            JOIN disease_keywords dk ON LOWER(c.diagnostic) LIKE dk.pattern
            WHERE c.statut = 'SIGNE'
              AND c.diagnostic IS NOT NULL
              AND cab.ville IS NOT NULL
              AND cab.latitude IS NOT NULL
              AND cab.longitude IS NOT NULL
              AND c.date >= NOW() - make_interval(days => :days_back)
              {signal_filter}
            GROUP BY cab.ville, cab.latitude, cab.longitude, dk.category
        ),
        anomalies AS (
            SELECT DISTINCT region, signal
            FROM epidemiology_alerts
            WHERE "createdAt" >= NOW() - make_interval(days => :days_back)
        )
        SELECT
            cc.ville,
            cc.latitude,
            cc.longitude,
            cc.disease,
            cc.case_count,
            CASE WHEN a.region IS NOT NULL THEN true ELSE false END AS is_anomaly
        FROM case_counts cc
        LEFT JOIN anomalies a ON a.region = cc.ville AND a.signal = cc.disease
        ORDER BY cc.case_count DESC
    """)

    params: dict = {"days_back": days_back}
    if signal:
        params["signal"] = signal

    try:
        result = await db.execute(query, params)
        rows = result.mappings().fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error(f"Failed to fetch heatmap data: {e}", exc_info=True)
        raise


async def create_cabinet_alert(
    db: AsyncSession,
    cabinet_id: str,
    title: str,
    description: str,
    severity: str,
    metadata: Dict[str, Any],
) -> Optional[str]:
    """
    Create a clinical alert in the main alerts table (visible in doctor UI).

    Uses type=CLINICAL, patientId=NULL (population-level).
    """
    # Dedup check
    check_query = text("""
        SELECT COUNT(*) FROM alerts
        WHERE title = :title AND status = 'ACTIVE' AND "patientId" IS NULL
    """)
    result = await db.execute(check_query, {"title": title})
    if result.scalar() > 0:
        return None

    safe_severity = severity.replace("'", "''")
    insert_query = text(f"""
        INSERT INTO alerts (
            id, "cabinetId", "patientId", type, severity,
            title, description, status, metadata, "createdAt"
        )
        VALUES (
            gen_random_uuid()::text, :cabinet_id, NULL,
            'CLINICAL'::"AlertType", '{safe_severity}'::"AlertSeverity",
            :title, :description, 'ACTIVE'::"AlertStatus",
            CAST(:metadata AS jsonb), NOW()
        )
        RETURNING id
    """)

    try:
        result = await db.execute(insert_query, {
            "cabinet_id": cabinet_id,
            "title": title,
            "description": description,
            "metadata": json.dumps(metadata),
        })
        return result.scalar_one()
    except Exception as e:
        logger.error(f"Failed to create cabinet alert: {e}", exc_info=True)
        raise
