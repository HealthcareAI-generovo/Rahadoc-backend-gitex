"""
Raw async SQL queries for fetching patient context and writing audit logs.
Uses SQLAlchemy Core (not ORM) for performance.
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


async def get_patient_context(
    db: AsyncSession,
    patient_id: str,
    cabinet_id: str
) -> Dict[str, Any]:
    """
    Fetch complete patient context for AI processing.

    Returns:
        Dictionary with patient info, antecedents, allergies, current treatments,
        recent consultations, and active protocols.
    """
    try:
        # Get patient info
        patient_query = text("""
            SELECT id, nom, prenom, "dateNaissance", sexe, "groupeSanguin",
                   antecedents, allergies, traitements
            FROM patients
            WHERE id = :patient_id AND "cabinetId" = :cabinet_id AND "isDeleted" = false
        """)

        result = await db.execute(
            patient_query,
            {"patient_id": patient_id, "cabinet_id": cabinet_id}
        )
        patient = result.mappings().first()

        if not patient:
            raise ValueError(f"Patient {patient_id} not found")

        # Get recent consultations (last 5)
        consultations_query = text("""
            SELECT id, date, motif, diagnostic, plan
            FROM consultations
            WHERE "patientId" = :patient_id AND "cabinetId" = :cabinet_id
            ORDER BY date DESC
            LIMIT 5
        """)

        result = await db.execute(
            consultations_query,
            {"patient_id": patient_id, "cabinet_id": cabinet_id}
        )
        consultations = [dict(row._mapping) for row in result]

        # Get active protocols
        protocols_query = text("""
            SELECT p.nom, p.pathologie, pp."dateDebut"
            FROM patient_protocols pp
            JOIN protocols p ON pp."protocolId" = p.id
            WHERE pp."patientId" = :patient_id AND pp.actif = true
        """)

        result = await db.execute(protocols_query, {"patient_id": patient_id})
        protocols = [dict(row._mapping) for row in result]

        return {
            "patient": dict(patient),
            "consultations": consultations,
            "protocols": protocols
        }

    except Exception as e:
        logger.error(f"Error fetching patient context: {e}")
        raise


async def get_consultation_data(
    db: AsyncSession,
    consultation_id: str,
    cabinet_id: str
) -> Dict[str, Any]:
    """Fetch consultation data for AI processing."""
    query = text("""
        SELECT c.*, p.nom as patient_nom, p.prenom as patient_prenom,
               p."dateNaissance", p.sexe, p.antecedents, p.allergies, p.traitements
        FROM consultations c
        JOIN patients p ON c."patientId" = p.id
        WHERE c.id = :consultation_id AND c."cabinetId" = :cabinet_id
    """)

    result = await db.execute(
        query,
        {"consultation_id": consultation_id, "cabinet_id": cabinet_id}
    )
    row = result.mappings().first()

    if not row:
        raise ValueError(f"Consultation {consultation_id} not found")

    return dict(row)


async def get_ordonnance_lines(
    db: AsyncSession,
    ordonnance_id: str,
    cabinet_id: str
) -> List[Dict[str, Any]]:
    """Fetch prescription lines for Rx Guard processing."""
    query = text("""
        SELECT lo.*
        FROM lignes_ordonnance lo
        JOIN ordonnances o ON lo."ordonnanceId" = o.id
        WHERE o.id = :ordonnance_id AND o."cabinetId" = :cabinet_id
    """)

    result = await db.execute(
        query,
        {"ordonnance_id": ordonnance_id, "cabinet_id": cabinet_id}
    )

    return [dict(row._mapping) for row in result]


async def write_ai_audit_log(
    db: AsyncSession,
    cabinet_id: str,
    action_type: str,
    input_text: str,
    output_text: str,
    model: str,
    provider: str,
    user_id: Optional[str] = None,
    patient_id: Optional[str] = None,
    response_time_ms: Optional[int] = None,
    accepted: Optional[bool] = None,
    edited_output: Optional[str] = None
) -> str:
    """
    Write AI audit log entry.

    Returns:
        The created audit log ID.
    """
    try:
        query = text("""
            INSERT INTO ai_audit_logs (
                "cabinetId", "userId", "patientId", type, input, output,
                model, provider, accepted, "editedOutput", "responseTimeMs", "createdAt"
            )
            VALUES (
                :cabinet_id, :user_id, :patient_id, :action_type::\"AIActionType\",
                :input_text, :output_text, :model, :provider, :accepted,
                :edited_output, :response_time_ms, NOW()
            )
            RETURNING id
        """)

        result = await db.execute(query, {
            "cabinet_id": cabinet_id,
            "user_id": user_id,
            "patient_id": patient_id,
            "action_type": action_type,
            "input_text": input_text,
            "output_text": output_text,
            "model": model,
            "provider": provider,
            "accepted": accepted,
            "edited_output": edited_output,
            "response_time_ms": response_time_ms
        })

        await db.commit()

        audit_id = result.scalar_one()
        logger.info(f"AI audit log created: {audit_id}")
        return audit_id

    except Exception as e:
        logger.error(f"Error writing AI audit log: {e}")
        await db.rollback()
        raise
