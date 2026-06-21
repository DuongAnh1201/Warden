"""Deepgram STT + TTS — real-time streaming with fast endpointing."""
from __future__ import annotations

import asyncio
import base64
import logging
import queue
import threading
import time
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
        self._speaking = False    # True only while TTS audio is playing (echo suppression)
        self._stopped = False     # set on stop() to break the reconnect loop

    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        threading.Thread(target=self._run_stt, daemon=True).start()

    def _run_stt(self) -> None:
        """Listen for transcripts, reconnecting whenever the Deepgram stream closes.

        Flux/streaming models routinely close the socket after an end-of-turn or an
        idle gap. Without a reconnect loop the daemon thread dies after the first
        turn and nothing is ever transcribed again — so we loop until stop().
        """
        client = DeepgramClient(api_key=settings.deepgram_api_key)
        while not self._stopped:
            try:
                self._connect_and_listen(client)
            except Exception as exc:  # noqa: BLE001
                logger.error("[stt] connection error: %s", exc)
            if not self._stopped:
                logger.warning("[stt] stream closed — reconnecting")
                time.sleep(0.3)
        logger.info("[stt] listener stopped")

    def _connect_and_listen(self, client: DeepgramClient) -> None:
        with client.listen.v2.connect(
            model=STT_MODEL,
            encoding="linear16",
            sample_rate=INPUT_SAMPLE_RATE,
            eager_eot_threshold=0.7,
            eot_timeout_ms=1000,
        ) as conn:
            logger.info("[stt] connection open (model=%s)", STT_MODEL)

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
                if event != "EndOfTurn" or not transcript:
                    return
                if self._speaking:
                    # Agent is talking — this is almost certainly its own TTS
                    # bleeding into the mic, not the user. Suppress it.
                    logger.info("[stt] dropped turn (agent speaking): %s", transcript)
                    return
                if not self._loop:
                    return
                logger.info("[stt] EndOfTurn: %s", transcript)
                asyncio.run_coroutine_threadsafe(self._dispatch(transcript), self._loop)

            conn.on(EventType.MESSAGE, on_message)
            conn.on(EventType.ERROR, lambda e: logger.error("[stt] %s", e))

            # Drain audio into THIS connection until it closes or we stop.
            active = threading.Event()
            active.set()

            def drain() -> None:
                while active.is_set():
                    try:
                        chunk = self._audio_queue.get(timeout=0.5)
                    except queue.Empty:
                        continue
                    if chunk is None:  # stop sentinel
                        self._stopped = True
                        active.clear()
                        try:
                            conn.finish()
                        except Exception:  # noqa: BLE001
                            pass
                        return
                    try:
                        conn.send_media(chunk)
                    except Exception as exc:  # noqa: BLE001
                        logger.error("[stt] send_media failed: %s", exc)
                        active.clear()
                        return

            threading.Thread(target=drain, daemon=True).start()
            try:
                conn.start_listening()  # blocks until the stream closes
            finally:
                active.clear()  # stop this connection's drain thread
                logger.info("[stt] connection closed")

    async def _dispatch(self, transcript: str) -> None:
        await self._on_transcript(transcript)

    async def send_audio(self, base64_data: str) -> None:
        self._audio_queue.put(base64.b64decode(base64_data))

    async def speak(self, text: str) -> None:
        loop = asyncio.get_running_loop()
        client = DeepgramClient(api_key=settings.deepgram_api_key)

        # Suppress STT while we play audio so the agent's own voice isn't
        # transcribed back as a user turn (acoustic echo).
        self._speaking = True

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

        try:
            await asyncio.to_thread(_run)
        finally:
            self._speaking = False

    async def stop(self) -> None:
        self._stopped = True
        self._audio_queue.put(None)
