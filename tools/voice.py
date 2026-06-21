"""Deepgram live STT + TTS.

Two modes
---------
Microphone (default):
    uv run python -m tools.voice

Stream from URL (translation of the shell script):
    uv run python -m tools.voice --stream <url>

    Requires ffmpeg on PATH. Audio is fetched, converted to 16 kHz mono PCM
    by ffmpeg, and streamed to Deepgram v2 listen.

Public API (Phase 3 wiring)
----------------------------
    queue = asyncio.Queue()
    asyncio.create_task(run_stt_loop(client, state, queue))
    while True:
        transcript = await queue.get()
        result = await orchestrator.run(transcript, deps=deps)
        await speak_text(client, result.output.response)
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import threading
from dataclasses import dataclass, field

import numpy as np
import sounddevice as sd
from config import settings
from deepgram import DeepgramClient
from deepgram.core.events import EventType
try:
    from deepgram.listen.v2.types import ListenV2TurnInfo  # type: ignore[import-untyped]
except ImportError:
    ListenV2TurnInfo = None  # type: ignore[assignment,misc]
from deepgram.speak.v1.types.speak_v1text import SpeakV1Text        # type: ignore[import-untyped]
from deepgram.speak.v1.types.speak_v1flushed import SpeakV1Flushed  # type: ignore[import-untyped]

_FINAL_EVENTS = {"EndOfTurn", "EagerEndOfTurn"}

API_KEY   = settings.deepgram_api_key
STT_MODEL = settings.transcription_model or "flux-general-en"
TTS_MODEL = settings.voice_model or "aura-2-athena-en"

INPUT_SAMPLE_RATE = 16000
TTS_SAMPLE_RATE   = 24000
CHANNELS  = 1
DTYPE     = "int16"
CHUNK     = 4096  # bytes per send to Deepgram


@dataclass
class AppState:
    speaking: bool = False
    last_final_transcript: str = ""
    transcript_queue: asyncio.Queue[str] = field(default_factory=asyncio.Queue)


# ── TTS ───────────────────────────────────────────────────────────────────────

async def speak_text(client: DeepgramClient, text: str) -> None:
    """Convert text to speech and play through speakers (streaming WebSocket for low latency)."""
    audio_chunks: list[bytes] = []

    def _run() -> None:
        with client.speak.v1.connect(
            model=TTS_MODEL,
            encoding="linear16",
            sample_rate=TTS_SAMPLE_RATE,
        ) as conn:
            def on_msg(msg) -> None:
                if isinstance(msg, bytes):
                    audio_chunks.append(msg)
                elif isinstance(msg, SpeakV1Flushed):
                    conn.send_close()

            conn.on(EventType.MESSAGE, on_msg)
            conn.on(EventType.ERROR,   lambda e: _err(f"TTS: {e}"))
            conn.send_text(SpeakV1Text(text=text))
            conn.send_flush()
            conn.start_listening()

    await asyncio.to_thread(_run)

    if audio_chunks:
        audio = np.frombuffer(b"".join(audio_chunks), dtype=np.int16)
        sd.play(audio, TTS_SAMPLE_RATE)
        await asyncio.to_thread(sd.wait)


# ── shared on_message handler ─────────────────────────────────────────────────

def _make_handler(
    state: AppState,
    queue: asyncio.Queue[str],
    loop: asyncio.AbstractEventLoop,
    client: DeepgramClient,
    *,
    tts_enabled: bool = True,
):
    """Return the on_message callback used by both mic and stream modes."""

    def on_message(msg) -> None:
        # SDK v2 delivers raw dicts; fall back to attribute access for typed wrappers.
        if isinstance(msg, dict):
            data = msg
        elif isinstance(msg, ListenV2TurnInfo):
            data = {
                "event": msg.event,
                "turn_index": msg.turn_index,
                "transcript": msg.transcript,
                "end_of_turn_confidence": msg.end_of_turn_confidence,
            }
        else:
            return

        event      = data.get("event", "")
        turn       = data.get("turn_index", 0)
        transcript = (data.get("transcript") or "").strip()
        confidence = data.get("end_of_turn_confidence") or 0.0

        if event == "StartOfTurn":
            print(f"--- StartOfTurn (Turn {turn}) ---", flush=True)

        if transcript:
            # Partials overwrite the line; finals commit it.
            if event == "Update":
                print(f"\r{transcript}", end="", flush=True)
            else:
                print(f"\r{transcript}", flush=True)

        if event == "EndOfTurn":
            print(f"--- EndOfTurn (Turn {turn}, Confidence: {confidence:.2f}) ---",
                  flush=True)
            if transcript:
                state.last_final_transcript = transcript
                asyncio.run_coroutine_threadsafe(queue.put(transcript), loop)

        if event in _FINAL_EVENTS and transcript and tts_enabled and not state.speaking:
            async def _speak() -> None:
                state.speaking = True
                try:
                    await speak_text(client, f"I heard: {transcript}. Thank you.")
                finally:
                    state.speaking = False
            asyncio.run_coroutine_threadsafe(_speak(), loop)

    return on_message


# ── Microphone mode ───────────────────────────────────────────────────────────

async def run_stt_loop(
    client: DeepgramClient,
    state: AppState,
    transcript_queue: asyncio.Queue[str] | None = None,
) -> None:
    """Stream microphone audio to Deepgram STT. Runs until cancelled."""
    queue = transcript_queue or state.transcript_queue
    loop  = asyncio.get_running_loop()
    handler = _make_handler(state, queue, loop, client, tts_enabled=True)

    with client.listen.v2.connect(
        model=STT_MODEL,
        encoding="linear16",
        sample_rate=INPUT_SAMPLE_RATE,
    ) as conn:
        conn.on(EventType.OPEN,    lambda _: print("[voice] STT connected", file=sys.stderr, flush=True))
        conn.on(EventType.CLOSE,   lambda _: print("[voice] STT closed",    file=sys.stderr, flush=True))
        conn.on(EventType.MESSAGE, handler)
        conn.on(EventType.ERROR,   lambda e: _err(f"STT: {e}"))

        def audio_callback(indata, _frames, _time_info, status) -> None:
            if not state.speaking:
                conn.send_media(bytes(indata))

        with sd.RawInputStream(
            samplerate=INPUT_SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            callback=audio_callback,
            blocksize=0,
        ):
            print("Listening…", file=sys.stderr, flush=True)
            await asyncio.to_thread(conn.start_listening)


# ── URL streaming mode (Python version of the shell script) ──────────────────

def _stream_ffmpeg(url: str, conn, stop_event: threading.Event) -> None:
    """Run ffmpeg to decode `url` → 16 kHz mono PCM and send chunks to Deepgram."""
    cmd = [
        "ffmpeg", "-loglevel", "error",
        "-i", url,
        "-f", "s16le", "-ar", str(INPUT_SAMPLE_RATE), "-ac", "1",
        "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        while not stop_event.is_set():
            chunk = proc.stdout.read(CHUNK)
            if not chunk:
                break
            conn.send_media(chunk)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


async def run_stream_loop(
    client: DeepgramClient,
    url: str,
    state: AppState | None = None,
    transcript_queue: asyncio.Queue[str] | None = None,
) -> None:
    """Stream audio from `url` via ffmpeg → Deepgram v2 STT.

    Mirrors the shell script exactly:
      - eager_eot_threshold=0.3, eot_threshold=0.7, eot_timeout_ms=5000
      - Prints StartOfTurn, transcript updates, and EndOfTurn with confidence.
    """
    if state is None:
        state = AppState()
    queue = transcript_queue or state.transcript_queue
    loop  = asyncio.get_running_loop()
    # TTS not available in stream mode (no speakers wired to a radio stream).
    handler = _make_handler(state, queue, loop, client, tts_enabled=False)

    stop_event = threading.Event()

    with client.listen.v2.connect(
        model=STT_MODEL,
        encoding="linear16",
        sample_rate=INPUT_SAMPLE_RATE,
        eager_eot_threshold=0.3,
        eot_threshold=0.7,
        eot_timeout_ms=5000,
    ) as conn:
        conn.on(EventType.OPEN,    lambda _: print("[voice] stream connected", file=sys.stderr, flush=True))
        conn.on(EventType.CLOSE,   lambda _: print("[voice] stream closed",    file=sys.stderr, flush=True))
        conn.on(EventType.MESSAGE, handler)
        conn.on(EventType.ERROR,   lambda e: _err(f"STT: {e}"))

        ffmpeg_thread = threading.Thread(
            target=_stream_ffmpeg, args=(url, conn, stop_event), daemon=True
        )
        ffmpeg_thread.start()
        print(f"Streaming {url}", file=sys.stderr, flush=True)

        try:
            await asyncio.to_thread(conn.start_listening)
        finally:
            stop_event.set()
            ffmpeg_thread.join(timeout=5)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _err(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)


# ── Entry point ───────────────────────────────────────────────────────────────

async def _run(args: list[str]) -> int:
    if not API_KEY:
        _err("DEEPGRAM_API_KEY is not set. Add it to .env")
        return 1

    client = DeepgramClient()
    state  = AppState()

    # --stream <url>  →  URL streaming mode
    if len(args) >= 2 and args[0] == "--stream":
        url = args[1]
        try:
            await run_stream_loop(client, url, state)
        except KeyboardInterrupt:
            print("\nStopped.", flush=True)
        return 0

    # default  →  microphone mode
    try:
        await run_stt_loop(client, state)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    except Exception as exc:
        _err(f"Fatal: {exc}")
        return 1

    return 0


def main() -> int:
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    sys.stdout.reconfigure(line_buffering=True)
    return asyncio.run(_run(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
