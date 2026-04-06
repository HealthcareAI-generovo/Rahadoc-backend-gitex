"""
Azure OpenAI client wrapper for LLM and STT.
Provides structured interface for AI operations with Ollama fallback support.
"""
from openai import AzureOpenAI, AsyncAzureOpenAI
from typing import AsyncIterator, Optional, Dict, Any, Tuple
import logging
import asyncio
import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class AzureOpenAIService:
    """
    Wrapper around Azure OpenAI client with Ollama fallback.
    Handles both chat completions (LLM) and audio transcriptions (STT).
    On Azure failure, automatically falls back to Ollama.
    """

    def __init__(self):
        """Initialize Azure OpenAI clients."""
        self.client = AzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        )

        self.async_client = AsyncAzureOpenAI(
            api_key=settings.AZURE_OPENAI_API_KEY,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
        )

        self.deployment = settings.AZURE_OPENAI_DEPLOYMENT
        self.whisper_deployment = settings.AZURE_WHISPER_DEPLOYMENT or "whisper"
        self.ollama_url = settings.OLLAMA_URL
        self.ollama_model = settings.OLLAMA_MODEL

    async def _ollama_complete(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Fallback completion via Ollama.
        """
        if not self.ollama_url or not self.ollama_url.strip():
            raise ValueError("Ollama URL not configured (OLLAMA_URL is empty)")

        logger.info(f"Calling Ollama completion (model: {self.ollama_model})")

        async with httpx.AsyncClient(timeout=120.0) as client:
            payload = {
                "model": self.ollama_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }

            if response_format and response_format.get("type") == "json_object":
                payload["format"] = "json"

            response = await client.post(
                f"{self.ollama_url}/api/chat",
                json=payload
            )
            response.raise_for_status()

            result = response.json()
            content = result.get("message", {}).get("content", "")
            logger.info(f"Ollama completion successful ({len(content)} chars)")
            return content

    async def _azure_complete(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Primary completion via Azure OpenAI.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        logger.info(f"Calling Azure OpenAI completion (deployment: {self.deployment})")

        kwargs = {
            "model": self.deployment,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if response_format:
            kwargs["response_format"] = response_format

        response = await self.async_client.chat.completions.create(**kwargs)

        result = response.choices[0].message.content
        logger.info(f"Azure OpenAI completion successful ({len(result)} chars)")
        return result

    async def complete(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Get LLM completion (non-streaming) with Ollama fallback.

        Args:
            prompt: User prompt
            system_prompt: System instructions
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum response tokens
            response_format: Optional response format (e.g., {"type": "json_object"})

        Returns:
            Generated text response
        """
        return await self._azure_complete(
            prompt, system_prompt, temperature, max_tokens, response_format
        )

    async def complete_azure_only(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Get LLM completion strictly via Azure OpenAI.

        This bypasses any local fallback provider and surfaces Azure errors directly.
        """
        return await self._azure_complete(
            prompt, system_prompt, temperature, max_tokens, response_format
        )

    async def complete_with_provider(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        response_format: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, str]:
        """
        Get LLM completion with provider tracking.

        Returns:
            Tuple of (response_text, provider_used)
        """
        result = await self._azure_complete(
            prompt, system_prompt, temperature, max_tokens, response_format
        )
        return result, "azure_openai"

    async def stream(
        self,
        prompt: str,
        system_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> AsyncIterator[str]:
        """
        Get streaming LLM completion (for SSE).

        Args:
            prompt: User prompt
            system_prompt: System instructions
            temperature: Sampling temperature
            max_tokens: Maximum response tokens

        Yields:
            Text chunks as they arrive
        """
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ]

            logger.info(f"Starting Azure OpenAI stream (deployment: {self.deployment})")

            response = await self.async_client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True
            )

            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"Azure OpenAI streaming error: {e}", exc_info=True)
            raise

    async def transcribe_audio(
        self,
        audio_file: bytes,
        language: Optional[str] = None,
        filename: str = "audio.opus"
    ) -> str:
        """
        Transcribe audio using Azure OpenAI Whisper.

        Args:
            audio_file: Audio file bytes
            language: Optional language code (fr, ar, etc.)
            filename: Filename for the audio (must have extension)

        Returns:
            Transcribed text
        """
        try:
            logger.info(f"Transcribing audio ({len(audio_file)} bytes, lang: {language})")

            def normalize_filename(name: str) -> str:
                allowed = {
                    "flac", "m4a", "mp3", "mp4", "mpeg", "mpga", "oga", "ogg", "wav", "webm"
                }
                if not name or "." not in name:
                    return "audio.webm"
                ext = name.rsplit(".", 1)[-1].lower()
                if ext not in allowed:
                    return "audio.webm"
                return name

            normalized_filename = normalize_filename(filename)

            # Create a file-like object
            from io import BytesIO
            audio_buffer = BytesIO(audio_file)
            audio_buffer.name = normalized_filename

            kwargs = {
                "model": self.whisper_deployment,
                "file": audio_buffer,
            }

            if language:
                kwargs["language"] = language

            response = await self.async_client.audio.transcriptions.create(**kwargs)

            transcript = response.text
            logger.info(f"Transcription successful ({len(transcript)} chars)")
            return transcript

        except Exception as e:
            logger.error(f"Azure OpenAI transcription error: {e}", exc_info=True)
            raise


# Global service instance
azure_service = AzureOpenAIService()
