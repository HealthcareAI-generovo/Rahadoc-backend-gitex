"""
Rx Guard AI service (Layer 3) - advanced prescription checking.
"""
import logging
import json
from typing import Dict, Any, List

from app.services.azure_openai import azure_service
from app.prompts.rx_guard import RX_GUARD_SYSTEM_PROMPT, build_rx_guard_prompt
from app.models.rx_guard import RxGuardAlert, AlertSeverity, AlertType

logger = logging.getLogger(__name__)


class RxGuardAIService:
    """AI-powered prescription safety checking (Layer 3)."""

    async def check_prescription(
        self,
        patient_data: Dict[str, Any],
        ordonnance_lines: List[Dict[str, Any]],
        chronic_treatments: str = ""
    ) -> tuple[List[RxGuardAlert], bool]:
        """
        Check entire prescription using AI.

        Args:
            patient_data: Patient profile
            ordonnance_lines: List of prescription lines
            chronic_treatments: Current chronic treatments

        Returns:
            Tuple of (alerts_list, safe_to_sign)
        """
        logger.info(f"AI checking prescription with {len(ordonnance_lines)} lines")

        prompt = build_rx_guard_prompt(patient_data, ordonnance_lines, chronic_treatments)

        # Call LLM
        response = await azure_service.complete(
            prompt=prompt,
            system_prompt=RX_GUARD_SYSTEM_PROMPT,
            temperature=0.2,  # Low temperature for safety-critical task
            max_tokens=2000,
            response_format={"type": "json_object"}
        )

        # Parse JSON response
        try:
            data = json.loads(response)

            # Convert alerts
            alerts = []
            for alert_data in data.get("alerts", []):
                try:
                    alert = RxGuardAlert(
                        severity=AlertSeverity(alert_data["severity"]),
                        type=AlertType(alert_data["type"]),
                        medication=alert_data["medication"],
                        description=alert_data["description"],
                        recommendation=alert_data["recommendation"],
                        alternative=alert_data.get("alternative")
                    )
                    alerts.append(alert)
                except (KeyError, ValueError) as e:
                    logger.warning(f"Skipping malformed alert: {e}")
                    continue

            safe_to_sign = data.get("safe_to_sign", True)

            # Double-check: if any RED alerts, it's not safe to sign
            has_red = any(alert.severity == AlertSeverity.RED for alert in alerts)
            if has_red:
                safe_to_sign = False

            logger.info(f"AI check complete: {len(alerts)} alerts, safe={safe_to_sign}")
            return alerts, safe_to_sign

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse Rx Guard AI response: {e}")
            logger.error(f"Raw response: {response}")
            # Fail-safe: return empty alerts but mark as unsafe due to error
            return [], False


# Global instance
rx_guard_ai_service = RxGuardAIService()
