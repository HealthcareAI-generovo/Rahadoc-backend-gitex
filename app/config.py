"""
Configuration settings using pydantic-settings.
Loads from environment variables.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List


class Settings(BaseSettings):
    """Application settings loaded from environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # Azure OpenAI
    AZURE_OPENAI_API_KEY: str
    AZURE_OPENAI_ENDPOINT: str
    AZURE_OPENAI_API_VERSION: str = "2024-02-15-preview"
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-4"
    AZURE_WHISPER_DEPLOYMENT: str | None = None  # Optional separate Whisper deployment

    # Database (shared PostgreSQL with Next.js)
    DATABASE_URL: str

    # Security
    INTERNAL_API_SECRET: str
    CRON_SECRET: str | None = None

    # Fallback providers (optional)
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "mistral"
    LOCAL_WHISPER_URL: str | None = None

    # CORS
    ALLOWED_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:3001"]

    # Environment
    DEBUG: bool = False

    # AI Settings
    MAX_TOKENS: int = 2000
    TEMPERATURE: float = 0.7
    STREAMING_CHUNK_SIZE: int = 5  # seconds for ambient mode

    # Cache settings
    PATIENT_360_CACHE_TTL: int = 86400  # 24 hours in seconds

    # Epidemiology (optional — features degrade gracefully without these)
    RESEND_API_KEY: str | None = None
    ALERT_EMAIL_FROM: str = "RahaDoc <alerts@rahadoc.ma>"
    EPIDEMIOLOGY_ENABLE_ML: bool = True  # Enable Isolation Forest layer
    EPIDEMIOLOGY_ENABLE_ZSCORE: bool = True  # Enable Z-score layer

    # Simulation mode — generates synthetic consultation data for demo/testing
    SIMULATION_MODE: bool = False
    SIMULATION_INTERVAL_SECONDS: int = 45  # How often to generate a batch
    SIMULATION_SEED: int | None = None     # Fixed seed for reproducibility (None = random)

    # OCR settings (Lab Results Explainer)
    OCR_LANGUAGES: str = "fra+eng+ara"          # Tesseract language string
    TESSERACT_CMD: str | None = None            # Override Tesseract binary path (e.g. /usr/bin/tesseract)


# Create global settings instance
settings = Settings()
