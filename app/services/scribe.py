"""
MedScribe service - handles audio transcription and structuring.
"""
import logging
import json
from typing import Dict, Any

from app.services.azure_openai import azure_service
from app.services.audit import audit_logger, AICallTimer
from app.prompts.scribe import MEDSCRIBE_SYSTEM_PROMPT, build_medscribe_prompt
from app.models.scribe import StructuredConsultation

logger = logging.getLogger(__name__)


class MedScribeService:
    """Service for MedScribe dictation and ambient mode."""

    async def process_dictation(
        self,
        audio_bytes: bytes,
        patient_context: Dict[str, Any],
        language: str | None = None,
        filename: str = "dictation.webm"
    ) -> tuple[str, str, StructuredConsultation]:
        """
        Process audio dictation: transcribe + structure.

        Args:
            audio_bytes: Audio file bytes
            patient_context: Patient medical context
            language: Optional language hint

        Returns:
            Tuple of (transcript, detected_language, structured_consultation)
        """
        logger.info(f"Processing dictation ({len(audio_bytes)} bytes)")

        # Step 1: Transcribe audio
        transcript = await azure_service.transcribe_audio(
            audio_file=audio_bytes,
            language=language,
            filename=filename
        )

        # Detect language (simple heuristic)
        detected_lang = self._detect_language(transcript)
        logger.info(f"Detected language: {detected_lang}")

        # Step 2: Structure with LLM
        structured = await self._structure_transcript(transcript, patient_context)

        return transcript, detected_lang, structured

    async def _structure_transcript(
        self,
        transcript: str,
        patient_context: Dict[str, Any]
    ) -> StructuredConsultation:
        """
        Structure transcript using Azure OpenAI LLM.

        Args:
            transcript: Raw transcription
            patient_context: Patient context dict

        Returns:
            Structured consultation object
        """
        prompt = build_medscribe_prompt(transcript, patient_context)

        # Call LLM with JSON response format
        response = await azure_service.complete(
            prompt=prompt,
            system_prompt=MEDSCRIBE_SYSTEM_PROMPT,
            temperature=0.3,  # Lower temperature for structured output
            max_tokens=1500,
            response_format={"type": "json_object"}
        )

        # Parse JSON response
        try:
            structured_data = json.loads(response)
            return StructuredConsultation(**structured_data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse structured response: {e}")
            logger.error(f"Raw response: {response}")
            # Return empty structure if parsing fails
            return StructuredConsultation()

    @staticmethod
    def _detect_language(text: str) -> str:
        """
        Simple language detection heuristic.

        Args:
            text: Text to analyze

        Returns:
            Language code (fr, ar, darija)
        """
        # Count Arabic characters
        arabic_chars = sum(1 for c in text if '\u0600' <= c <= '\u06FF')
        total_chars = len(text.strip())

        if total_chars == 0:
            return "fr"

        arabic_ratio = arabic_chars / total_chars

        if arabic_ratio > 0.3:
            # High Arabic content - could be standard Arabic or Darija
            # For now, default to Arabic (refinement would need NLP)
            return "ar"
        else:
            return "fr"


# Global instance
medscribe_service = MedScribeService()
