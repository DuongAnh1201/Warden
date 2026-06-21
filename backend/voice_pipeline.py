"""Deepgram STT + TTS — real-time streaming with fast endpointing."""
from __future__ import annotations

import asyncio
import base64
import logging
import queue
import threading
from collections.abc import Awaitable, Callable
from typing import Any

from deepgram import DeepgramClient
from deepgram.core.events import EventType
from deepgram.speak.v1.types.speak_v1text import SpeakV1Text        # type: ignore[import-untyped]
from deepgram.speak.v1.types.speak_v1flushed import SpeakV1Flushed  # type: ignore[import-untyped]

from config import settings

logger = logging.getLogger(__name__)

STT_MODEL = settings.transcription_model or "flux-general-en"
TTS_MODEL = settings.voice_model or "aura-2-athena-en"
INPUT_SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000


class VoicePipeline:
    def __init__(
        self,
        on_transcript: Callable[[str], Awaitable[None]],
        on_audio_chunk: Callable[[str], Awaitable[None]],
    ) -> None:
        self._on_transcript = on_transcript
        self._on_audio_chunk = on_audio_chunk
        self._audio_queue: queue.Queue[bytes | None] = queue.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._processing = False  # prevent overlapping runs

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        threading.Thread(target=self._run_stt, daemon=True).start()

    def _run_stt(self) -> None:
        client = DeepgramClient(api_key=settings.deepgram_api_key)

        with client.listen.v2.connect(
            model=STT_MODEL,
            encoding="linear16",
            sample_rate=INPUT_SAMPLE_RATE,
            eager_eot_threshold=0.7,
            eot_timeout_ms=1000,
        ) as conn:
            def on_message(msg: Any) -> None:
                if isinstance(msg, dict):
                    data = msg
                else:
                    try:
                        data = {"event": msg.event, "transcript": msg.transcript}
                    except AttributeError:
                        return
                event = data.get("event", "")
                transcript = (data.get("transcript") or "").strip()
                if event == "EndOfTurn" and transcript and not self._processing and self._loop:
                    self._processing = True
                    asyncio.run_coroutine_threadsafe(
                        self._dispatch(transcript), self._loop
                    )

            conn.on(EventType.MESSAGE, on_message)
            conn.on(EventType.ERROR, lambda e: logger.error("[stt] %s", e))

            def drain() -> None:
                while True:
                    chunk = self._audio_queue.get()
                    if chunk is None:
                        conn.finish()
                        break
                    conn.send_media(chunk)

            threading.Thread(target=drain, daemon=True).start()
            conn.start_listening()

    async def _dispatch(self, transcript: str) -> None:
        try:
            await self._on_transcript(transcript)
        finally:
            self._processing = False

    async def send_audio(self, base64_data: str) -> None:
        self._audio_queue.put(base64.b64decode(base64_data))

    async def speak(self, text: str) -> None:
        loop = asyncio.get_running_loop()
        client = DeepgramClient(api_key=settings.deepgram_api_key)

        def _run() -> None:
            with client.speak.v1.connect(
                model=TTS_MODEL,
                encoding="linear16",
                sample_rate=TTS_SAMPLE_RATE,
            ) as conn:
                def on_msg(msg: Any) -> None:
                    if isinstance(msg, bytes):
                        chunk_b64 = base64.b64encode(msg).decode()
                        asyncio.run_coroutine_threadsafe(
                            self._on_audio_chunk(chunk_b64), loop
                        ).result()
                    elif isinstance(msg, SpeakV1Flushed):
                        conn.send_close()

                conn.on(EventType.MESSAGE, on_msg)
                conn.send_text(SpeakV1Text(text=text))
                conn.send_flush()
                conn.start_listening()

        await asyncio.to_thread(_run)

    async def stop(self) -> None:
        self._audio_queue.put(None)
