"""
AI audit logging service.
Writes all AI calls to the AIAuditLog table for compliance and analysis.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import logging
import time

from app.db.queries import write_ai_audit_log

logger = logging.getLogger(__name__)


class AuditLogger:
    """Helper for logging AI operations."""

    @staticmethod
    async def log_ai_call(
        db: AsyncSession,
        cabinet_id: str,
        action_type: str,  # SCRIBE, DIAGNOSTIC, PRESCRIPTION, SUMMARY, etc.
        input_text: str,
        output_text: str,
        model: str,
        provider: str = "azure_openai",
        user_id: Optional[str] = None,
        patient_id: Optional[str] = None,
        response_time_ms: Optional[int] = None,
        accepted: Optional[bool] = None,
        edited_output: Optional[str] = None
    ) -> Optional[str]:
        """
        Log an AI call to the audit table.

        This is fire-and-forget - errors are logged but not raised
        to avoid breaking the main AI flow.

        Returns:
            Audit log ID if successful, None if failed
        """
        try:
            audit_id = await write_ai_audit_log(
                db=db,
                cabinet_id=cabinet_id,
                action_type=action_type,
                input_text=input_text[:10000],  # Truncate if too long
                output_text=output_text[:10000],
                model=model,
                provider=provider,
                user_id=user_id,
                patient_id=patient_id,
                response_time_ms=response_time_ms,
                accepted=accepted,
                edited_output=edited_output
            )

            logger.info(f"AI call logged: {action_type} (audit_id: {audit_id})")
            return audit_id

        except Exception as e:
            # Don't fail the main operation if audit logging fails
            logger.error(f"Failed to log AI call: {e}", exc_info=True)
            return None


# Context manager for timing AI operations
class AICallTimer:
    """Context manager to time AI operations."""

    def __init__(self):
        self.start_time = None
        self.elapsed_ms = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            self.elapsed_ms = int((time.time() - self.start_time) * 1000)


# Global instance
audit_logger = AuditLogger()
