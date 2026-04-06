"""
Lab Analysis AI service.
Sends OCR-extracted text to Azure OpenAI and parses structured explanation.
"""
import logging
import json
from typing import Optional

from app.services.azure_openai import azure_service
from app.prompts.lab_analysis import SYSTEM_PROMPTS, DISCLAIMERS, build_lab_analysis_prompt
from app.models.lab_analysis import (
    LabAnalysisResponse,
    KeyFinding,
    ExplanationItem,
    ComparisonNote,
)

logger = logging.getLogger(__name__)


class LabAnalysisService:

    async def analyze(
        self,
        lab_result_id: str,
        extracted_text: str,
        patient_age: Optional[int],
        patient_gender: Optional[str],
        language: str = "FR",
        ocr_confidence: float = 1.0,
        previous_findings: Optional[list] = None,
    ) -> LabAnalysisResponse:
        """
        Send extracted lab text to AI and parse structured explanation.
        """
        system_prompt = SYSTEM_PROMPTS.get(language, SYSTEM_PROMPTS["FR"])
        disclaimer = DISCLAIMERS.get(language, DISCLAIMERS["FR"])

        user_prompt = build_lab_analysis_prompt(
            extracted_text=extracted_text,
            patient_age=patient_age,
            patient_gender=patient_gender,
            language=language,
            previous_findings=previous_findings,
        )

        try:
            raw_response = await azure_service.complete(
                prompt=user_prompt,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=2500,
                response_format={"type": "json_object"},
            )
        except Exception as e:
            logger.error(f"AI completion failed for lab result {lab_result_id}: {e}", exc_info=True)
            raise

        # Parse JSON response
        try:
            data = json.loads(raw_response)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"AI returned non-JSON response: {raw_response[:200]}")

        # Parse key_findings
        key_findings = []
        for f in data.get("key_findings", []):
            key_findings.append(KeyFinding(
                name=f.get("name", ""),
                value=str(f.get("value", "")),
                unit=f.get("unit"),
                reference_range=f.get("reference_range"),
                status=f.get("status", "normal"),
            ))

        # Parse explanations
        explanations = []
        for e in data.get("explanation", []):
            explanations.append(ExplanationItem(
                marker=e.get("marker", ""),
                simple_explanation=e.get("simple_explanation", ""),
                possible_causes=e.get("possible_causes", []),
            ))

        # Parse recommendations
        recommendations = data.get("recommendations", [])

        # Determine confidence from AI + OCR quality
        ai_confidence = data.get("confidence", "MEDIUM")
        final_confidence = self._merge_confidence(ai_confidence, ocr_confidence)

        # Parse comparison notes if previous findings provided
        comparison_notes = []
        if previous_findings and data.get("comparison_notes"):
            for cn in data.get("comparison_notes", []):
                comparison_notes.append(ComparisonNote(
                    marker=cn.get("marker", ""),
                    change=cn.get("change", ""),
                    direction=cn.get("direction", "stable"),
                ))

        from datetime import datetime
        return LabAnalysisResponse(
            lab_result_id=lab_result_id,
            status="COMPLETED",
            summary=data.get("summary"),
            key_findings=key_findings if key_findings else None,
            explanation=explanations if explanations else None,
            recommendations=recommendations if recommendations else None,
            confidence=final_confidence,
            disclaimer=disclaimer,
            comparison_notes=comparison_notes if comparison_notes else None,
            analyzed_at=datetime.utcnow().isoformat(),
        )

    def _merge_confidence(self, ai_confidence: str, ocr_confidence: float) -> str:
        """
        Downgrade AI confidence if OCR quality was poor.
        """
        if ocr_confidence < 0.45:
            return "LOW"
        if ocr_confidence < 0.75 and ai_confidence == "HIGH":
            return "MEDIUM"
        return ai_confidence


lab_analysis_service = LabAnalysisService()
