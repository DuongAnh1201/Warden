"""Arize Phoenix setup — OTLP export + Pydantic AI auto-instrumentation.

Local (no API key):
    uv run phoenix serve
    # UI + collector at http://localhost:6006

Phoenix Cloud:
    Set PHOENIX_COLLECTOR_ENDPOINT and PHOENIX_API_KEY in .env
    See docs/observability/phoenix.md

When the collector is unreachable, tracing degrades gracefully — the in-process
consent evaluator still runs.
"""
from __future__ import annotations

import logging
import socket
from urllib.parse import urlparse

from observability.phoenix_config import (
    describe_phoenix_target,
    normalize_phoenix_collector_endpoint,
    phoenix_otlp_headers,
)

logger = logging.getLogger(__name__)

_initialized = False


def _endpoint_reachable(url: str, timeout: float = 1.5) -> bool:
    """Return True if a TCP connection to the OTLP endpoint succeeds within *timeout* seconds."""
    try:
        parsed = urlparse(url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 4318
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def setup_observability() -> bool:
    """Configure OpenTelemetry → Phoenix and instrument Pydantic AI. Idempotent."""
    global _initialized
    if _initialized:
        return True

    try:
        from config import settings
    except Exception:  # noqa: BLE001
        logger.debug("config unavailable — observability skipped")
        return False

    if not settings.phoenix_enabled:
        logger.info("Phoenix tracing disabled (PHOENIX_ENABLED=0)")
        _initialized = True
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from openinference.instrumentation.pydantic_ai import OpenInferenceSpanProcessor

        resource = Resource.create(
            {
                "service.name": settings.phoenix_project_name,
                "service.namespace": "moneypenny",
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(OpenInferenceSpanProcessor())

        endpoint = normalize_phoenix_collector_endpoint(settings.phoenix_collector_endpoint)
        headers = phoenix_otlp_headers(settings.phoenix_api_key)
        target = describe_phoenix_target(endpoint, settings.phoenix_api_key)

        try:
            if not _endpoint_reachable(endpoint):
                logger.info(
                    "Phoenix collector not reachable at %s — tracing disabled. "
                    "Run `uv run phoenix serve` to enable it.",
                    endpoint,
                )
            else:
                # Quiet down the OTLP background-thread noise so connection hiccups
                # don't spam the terminal after startup.
                logging.getLogger("opentelemetry.sdk.trace.export").setLevel(logging.CRITICAL)
                logging.getLogger("urllib3.connectionpool").setLevel(logging.WARNING)

                exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)
                provider.add_span_processor(BatchSpanProcessor(exporter))
                logger.info(
                    "Phoenix OTLP export → %s (%s, project=%s)",
                    endpoint,
                    target,
                    settings.phoenix_project_name,
                )
                if target.startswith("Phoenix Cloud") and "missing" in target:
                    logger.warning(
                        "Cloud endpoint configured without PHOENIX_API_KEY — "
                        "trace export will likely fail. See docs/observability/phoenix.md"
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Phoenix OTLP exporter not configured (%s) — in-process eval only", exc)

        trace.set_tracer_provider(provider)
        _instrument_pydantic_ai()
        _initialized = True
        return True
    except ImportError as exc:
        logger.warning("Phoenix dependencies not installed (%s) — observability skipped", exc)
        _initialized = True
        return False


def _instrument_pydantic_ai() -> None:
    """Enable OpenInference hooks for Pydantic AI agents (see get_agent_instrumentation)."""
    pass


def get_agent_instrumentation() -> list:
    """Return a capabilities list for Agent(capabilities=...) when Phoenix is enabled."""
    try:
        from config import settings

        if not settings.phoenix_enabled:
            return []
        from pydantic_ai.capabilities import Instrumentation
        from pydantic_ai.models.instrumented import InstrumentationSettings

        return [Instrumentation(InstrumentationSettings(version=2))]
    except Exception:  # noqa: BLE001
        return []
