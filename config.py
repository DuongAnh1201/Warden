"""
config.py — Application settings loaded from environment variables.

Usage anywhere in the project:
    from config import settings

    model = settings.ai_model
    key   = settings.serper_api_key
"""

from pydantic_settings import SettingsConfigDict
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider
from dotenv import load_dotenv
import os

load_dotenv()


class Settings:
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # silently ignore unrecognised env vars
    )

    env: str = os.getenv("LOGFIRE_ENVIRONMENT")

    # ── LLM ────────────────────────────────────────────────────────────────────
    ai_model: str = os.getenv("AI_MODEL")
    """PydanticAI model string. Examples:
       'google-gla:gemini-1.5-pro'   (Google Gemini via Generative Language API)
       'openai:gpt-4o'               (OpenAI)
    """
    # -- Realtime Audio ────────────────────────────────────────────────────────
    realtime_model: str = os.getenv("REALTIME_MODEL", "gpt-4o-mini-realtime-preview")
    """OpenAI Realtime model for native audio I/O."""

    realtime_voice: str = os.getenv("REALTIME_VOICE", "nova")
    """Realtime voice. Options: alloy, ash, ballad, coral, echo, sage, shimmer, verse."""
    base_url: str = os.getenv("BASE_URL")
    """Base URL for the API."""

    api_key: str = os.getenv("API_KEY")
    """API key for the API."""

    # ── API Keys ────────────────────────────────────────────────────────────────
    openai_api_key: str = os.getenv("OPENAI_API_KEY")
    """Required when ai_model starts with 'openai:'."""

    serper_api_key: str = os.getenv("SERPER_API_KEY")
    """Required for live event search in Agent 2 (Phase 4+)."""

    resend_api_key: str = os.getenv("RESEND_API_KEY", "")
    """Resend API key for sending emails."""

    resend_from: str = os.getenv("RESEND_FROM", "Moneypenny <onboarding@resend.dev>")
    """Sender address. Use a verified domain in production."""

    logfire_token: str = os.getenv("LOGFIRE_TOKEN")
    logfire_environment: str = os.getenv("LOGFIRE_ENVIRONMENT")
    """Required for Logfire integration."""

    file_path: str = os.getenv("FILE_PATH")
    """Path to the knowledge base."""

    redis_url: str = os.getenv("REDIS_URL", "")
    """Optional Redis connection URL (e.g. redis://localhost:6379).
    When set, the consent ledger uses Redis Streams; otherwise FileLedger (JSONL)."""
    deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
    voice_provider = os.getenv("VOICE_PROVIDER")
    transcription_model = os.getenv("TRANSCRIPTION_MODEL")
    voice_model = os.getenv("VOICE_MODEL")

    consent_secret: str = os.getenv(
        "CONSENT_SECRET", "moneypenny-dev-consent-secret-change-me"
    )
    """Server-side secret used to mint Consent_Tokens (HMAC-SHA256).
    MUST be overridden in production; the default is for local/demo only."""

    # ── Google Workspace (Drive / Gmail / Calendar) ──────────────────────────────
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    """OAuth client credentials for the user's Workspace connect flow."""

    google_redirect_uri: str = os.getenv(
        "GOOGLE_REDIRECT_URI", "http://localhost:8765/oauth2callback"
    )
    """Redirect URI registered with the Google OAuth client."""

    calendar_timezone: str = os.getenv("CALENDAR_TIMEZONE", "America/Los_Angeles")
    """IANA time zone applied to naive datetimes sent to Google Calendar."""

    workspace_token_path: str = os.getenv("WORKSPACE_TOKEN_PATH", ".workspace/credentials.enc")
    """Where the encrypted Workspace refresh token is stored (gitignored)."""

    workspace_token_key: str = os.getenv("WORKSPACE_TOKEN_KEY", "")
    """Secret used to encrypt the stored token at rest. Falls back to consent_secret."""


# Singleton — import this everywhere instead of instantiating Settings() yourself.
settings = Settings()
