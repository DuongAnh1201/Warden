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

    file_path: str = os.getenv("FILE_PATH")
    """Path to the knowledge base."""

    # DEMO: Redis disabled — the remote Redis Cloud reads are too slow for a live
    # demo (multi-second stalls after each action). Forcing this empty makes every
    # consumer fall back to its fast local path: FileLedger (JSONL) for the consent
    # ledger, in-memory/None for knowledge + execution log, and the Agentverse
    # bridge reports itself unavailable. Re-enable by restoring the os.getenv line.
    redis_url: str = ""
    # redis_url: str = os.getenv("REDIS_URL", "")
    """Optional Redis connection URL (e.g. redis://localhost:6379).
    When set, the consent ledger uses Redis Streams; otherwise FileLedger (JSONL).
    User memory / knowledge namespaces also use Redis when your teammate wires them up."""

    # ── Arize Phoenix (trust & observability) ───────────────────────────────────
    phoenix_enabled: bool = os.getenv("PHOENIX_ENABLED", "1") not in (
        "0",
        "false",
        "False",
        "",
    )
    """Export OpenTelemetry traces to Phoenix when enabled."""

    phoenix_collector_endpoint: str = os.getenv(
        "PHOENIX_COLLECTOR_ENDPOINT", "http://127.0.0.1:6006/v1/traces"
    )
    """OTLP HTTP endpoint for Phoenix. Local: `phoenix serve`. Cloud: space hostname."""

    phoenix_api_key: str = os.getenv("PHOENIX_API_KEY", "")
    """Bearer token for Phoenix Cloud OTLP export. Leave empty for local `phoenix serve`."""

    phoenix_project_name: str = os.getenv("PHOENIX_PROJECT_NAME", "moneypenny")

    consent_eval_enabled: bool = os.getenv("CONSENT_EVAL_ENABLED", "1") not in (
        "0",
        "false",
        "False",
        "",
    )
    """Run the self-check bypass evaluator after each gated action."""

    kill_switch_on_bypass: bool = os.getenv("KILL_SWITCH_ON_BYPASS", "1") not in (
        "0",
        "false",
        "False",
        "",
    )
    """When a consent bypass is detected, freeze the session (fail closed)."""
    deepgram_api_key = os.getenv("DEEPGRAM_API_KEY")
    voice_provider = os.getenv("VOICE_PROVIDER")
    transcription_model = os.getenv("TRANSCRIPTION_MODEL")
    voice_model = os.getenv("VOICE_MODEL")

    consent_secret: str = os.getenv(
        "CONSENT_SECRET", "moneypenny-dev-consent-secret-change-me"
    )


    # ── Fetch.ai / Agentverse ───────────────────────────────────────────────────
    fetch_agent_seed: str = os.getenv("FETCH_AGENT_SEED", "")
    """Stable seed phrase that determines MoneyPenny's Fetch.ai address.
    Generate once and keep it secret — changing it changes the address."""

    agentverse_api_key: str = os.getenv("AGENTVERSE_API_KEY", "")
    """Agentverse mailbox API key from agentverse.ai.
    Required for cloud hosting (receiving messages when not running locally)."""

    fetch_agent_port: int = int(os.getenv("PORT", os.getenv("FETCH_AGENT_PORT", "8001")))
    """Port the uAgent HTTP server listens on.
    Railway injects $PORT automatically; falls back to FETCH_AGENT_PORT, then 8001."""

    fetch_agent_endpoint: str = os.getenv(
        "FETCH_AGENT_ENDPOINT",
        ("https://" + os.getenv("RAILWAY_PUBLIC_DOMAIN")) if os.getenv("RAILWAY_PUBLIC_DOMAIN") else "",
    )
    """Public HTTPS URL where the uAgent is reachable.
    Auto-detected from $RAILWAY_PUBLIC_DOMAIN on Railway.
    Set FETCH_AGENT_ENDPOINT manually for other hosts (e.g. ngrok, Render).
    Leave empty to run in local/mailbox-only mode."""
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
