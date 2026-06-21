"""Deepgram STT + TTS pipeline for a single WebSocket session.

Audio flow:
  browser  →  base64 PCM16 @ 16kHz  →  Deepgram STT  →  transcript
  transcript  →  orchestrator  →  response text
  response text  →  Deepgram TTS  →  base64 PCM16 @ 24kHz  →  browser
"""
from __future__ import annotations

import asyncio
import base64
import logging
import threading
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

STT_MODEL = "flux-general-en"
TTS_MODEL = "aura-2-athena-en"
INPUT_SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000
TTS_CHUNK_BYTES = 4_096


class VoicePipeline:
    """Manages a live Deepgram STT connection + on-demand TTS for one session."""

    def __init__(
        self,
        on_transcript: Callable[[str], Awaitable[None]],
        on_audio_chunk: Callable[[str], Awaitable[None]],
    ) -> None:
        self._on_transcript = on_transcript
        self._on_audio_chunk = on_audio_chunk
        self._loop: asyncio.AbstractEventLoop | None = None
        self._conn: Any = None
        self._listen_thread: threading.Thread | None = None
        self._closed = False

    async def start(self) -> None:
        from config import settings
        from deepgram import DeepgramClient
        from deepgram.core.events import EventType

        self._loop = asyncio.get_running_loop()
        client = DeepgramClient(settings.deepgram_api_key)

        self._conn = client.listen.v2.connect(
            model=STT_MODEL,
            encoding="linear16",
            sample_rate=INPUT_SAMPLE_RATE,
        )
        self._conn.on(EventType.MESSAGE, self._on_stt_message)
        self._conn.on(EventType.ERROR, lambda e: logger.error("[stt] %s", e))

        self._listen_thread = threading.Thread(
            target=self._conn.start_listening, daemon=True
        )
        self._listen_thread.start()
        logger.info("[voice] STT connection opened")

    def _on_stt_message(self, msg: Any) -> None:
        if isinstance(msg, dict):
            event = msg.get("event", "")
            transcript = (msg.get("transcript") or "").strip()
            if event == "EndOfTurn" and transcript and self._loop:
                logger.info("[voice] EndOfTurn: %s", transcript[:80])
                asyncio.run_coroutine_threadsafe(
                    self._on_transcript(transcript), self._loop
                )

    async def send_audio(self, base64_data: str) -> None:
        if self._conn and not self._closed:
            raw = base64.b64decode(base64_data)
            await asyncio.to_thread(self._conn.send_media, raw)

    async def speak(self, text: str) -> None:
        from config import settings
        from deepgram import DeepgramClient
        from deepgram.core.events import EventType
        from deepgram.speak.v1.types.speak_v1text import SpeakV1Text
        from deepgram.speak.v1.types.speak_v1flushed import SpeakV1Flushed

        client = DeepgramClient(settings.deepgram_api_key)
        audio_chunks: list[bytes] = []

        def _run() -> None:
            with client.speak.v1.connect(
                model=TTS_MODEL,
                encoding="linear16",
                sample_rate=TTS_SAMPLE_RATE,
            ) as conn:
                def on_msg(msg: Any) -> None:
                    if isinstance(msg, bytes):
                        audio_chunks.append(msg)
                    elif isinstance(msg, SpeakV1Flushed):
                        conn.send_close()

                conn.on(EventType.MESSAGE, on_msg)
                conn.on(EventType.ERROR, lambda e: logger.error("[tts] %s", e))
                conn.send_text(SpeakV1Text(text=text))
                conn.send_flush()
                conn.start_listening()

        await asyncio.to_thread(_run)

        all_audio = b"".join(audio_chunks)
        for i in range(0, len(all_audio), TTS_CHUNK_BYTES):
            chunk_b64 = base64.b64encode(all_audio[i : i + TTS_CHUNK_BYTES]).decode()
            await self._on_audio_chunk(chunk_b64)

    async def stop(self) -> None:
        self._closed = True
        if self._conn:
            try:
                await asyncio.to_thread(self._conn.finish)
            except Exception:
                pass
            self._conn = None
