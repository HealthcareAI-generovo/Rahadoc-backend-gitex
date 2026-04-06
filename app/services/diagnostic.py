"""
Clinical Copilot service - provides diagnostic assistance.
"""
import logging
import json
from typing import Dict, Any, List

from app.services.azure_openai import azure_service
from app.prompts.diagnostic import DIAGNOSTIC_SYSTEM_PROMPT, build_diagnostic_prompt
from app.models.diagnostic import DiagnosticResponse, DiagnosticHypothesis

logger = logging.getLogger(__name__)


class ClinicalCopilotService:
    """Service for diagnostic assistance."""

    async def generate_hypotheses(
        self,
        patient_data: Dict[str, Any],
        consultation_data: Dict[str, Any]
    ) -> DiagnosticResponse:
        """
        Generate diagnostic hypotheses using Azure OpenAI.

        Args:
            patient_data: Patient demographics and history
            consultation_data: Current consultation details (motif, histoire, examen)

        Returns:
            DiagnosticResponse with ranked hypotheses
        """
        logger.info(f"Generating diagnostic hypotheses for patient {patient_data.get('id')}")

        prompt = build_diagnostic_prompt(patient_data, consultation_data)

        # Call LLM
        response = await azure_service.complete(
            prompt=prompt,
            system_prompt=DIAGNOSTIC_SYSTEM_PROMPT,
            temperature=0.5,  # Balanced creativity
            max_tokens=2000,
            response_format={"type": "json_object"}
        )

        # Parse JSON response
        try:
            data = json.loads(response)

            # Convert to Pydantic models
            hypotheses = [
                DiagnosticHypothesis(**h) for h in data.get("hypotheses", [])
            ]

            return DiagnosticResponse(
                hypotheses=hypotheses,
                red_flags=data.get("red_flags", []),
                suggested_exams=data.get("suggested_exams", [])
            )

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse diagnostic response: {e}")
            logger.error(f"Raw response: {response}")
            # Return empty response if parsing fails
            return DiagnosticResponse(
                hypotheses=[],
                red_flags=[],
                suggested_exams=[]
            )


# Global instance
copilot_service = ClinicalCopilotService()
