"""One WebSocket connection — owns OrchestratorDeps and routes client messages."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from ai.agents.orchestrator import get_orchestrator
from ai.session.deps_factory import build_orchestrator_deps

_SENT_RE = re.compile(r'(?<=[.!?…])\s+(?=[A-Z"\'])')


def _split_sentences(text: str) -> list[str]:
    parts = _SENT_RE.split(text.strip())
    return [p.strip() for p in parts if p.strip()]
from backend.approval import WebSocketApprover
from backend.protocol import serialize_ledger_entry
from backend.voice_pipeline import VoicePipeline
from observability.kill_switch import SessionFrozenError, assert_session_active

logger = logging.getLogger(__name__)


class AgentSession:
    """Phase 2 session handler: browser ↔ orchestrator over a single WebSocket."""

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket
        self._approver = WebSocketApprover(self.send_json)
        self._run_lock = asyncio.Lock()
        self._guest = False
        self._user_id = "default"
        self._deps = None
        self._started = False
        self._voice: VoicePipeline | None = None
        self._turns: list[dict[str, str]] = []

    async def send_json(self, payload: dict[str, Any]) -> None:
        await self._ws.send_text(json.dumps(payload))

    async def run(self) -> None:
        await self.send_json({"type": "session_ready"})
        await self.send_json({"type": "state", "speaking": False})

        try:
            while True:
                raw = await self._ws.receive_text()
                message = json.loads(raw)
                if not isinstance(message, dict):
                    continue
                await self.handle_message(message)
        except WebSocketDisconnect:
            logger.info("client disconnected user_id=%s", self._user_id)
        finally:
            self._approver.cancel_all()
            if self._voice:
                await self._voice.stop()
            await self._compact_session()

    async def handle_message(self, message: dict[str, Any]) -> None:
        msg_type = message.get("type")

        if msg_type == "ping":
            await self.send_json({"type": "pong"})
            return

        if msg_type == "session_start":
            self._guest = bool(message.get("guest"))
            self._user_id = str(message.get("user_id") or ("guest" if self._guest else "default"))
            self._deps = await build_orchestrator_deps(
                user_id=self._user_id,
                guest=self._guest,
                request_approval=self._approver,
                history=self._turns,
            )
            self._started = True
            await self.send_json(
                {
                    "type": "transcript",
                    "role": "assistant",
                    "text": (
                        "Good evening. I'm Désir — at your service. "
                        "What shall we handle first?"
                        if not self._guest
                        else "Welcome, Guest. I'm Désir in demo mode — try asking me to draft an email."
                    ),
                }
            )
            return

        if not self._started:
            self._deps = await build_orchestrator_deps(
                request_approval=self._approver,
                history=self._turns,
            )
            self._started = True

        if msg_type == "text":
            text = str(message.get("text", "")).strip()
            if text:
                await self.run_prompt(text)
            return

        if msg_type == "audio":
            data = str(message.get("data") or "")
            if data:
                if self._voice is None:
                    self._voice = VoicePipeline(
                        on_transcript=self._handle_voice_transcript,
                        on_audio_chunk=self._send_audio_chunk,
                    )
                    await self._voice.start()
                await self._voice.send_audio(data)
            return

        if msg_type == "approval_decision":
            action_id = str(message.get("action_id") or message.get("request_id") or "")
            decision = str(message.get("decision") or "cancel")
            note = str(message.get("revision_note") or message.get("note") or "")
            if action_id:
                self._approver.resolve(action_id, decision, revision_note=note)
            return

        if msg_type == "tool_result":
            return

        logger.debug("ignored message type=%s", msg_type)

    async def _handle_voice_transcript(self, transcript: str) -> None:
        await self.send_json({"type": "transcript", "role": "user", "text": transcript})
        await self.run_prompt(transcript, tts=True)

    async def _send_audio_chunk(self, base64_data: str) -> None:
        await self.send_json({"type": "audio", "data": base64_data})

    async def run_prompt(self, prompt: str, *, tts: bool = False) -> None:
        async with self._run_lock:
            try:
                assert_session_active()
            except SessionFrozenError as exc:
                await self.send_json({"type": "error", "message": str(exc)})
                return

            assert self._deps is not None
            logger.info("[user]  %s", prompt)
            await self.send_json({"type": "transcript", "role": "user", "text": prompt})
            await self.send_json({"type": "state", "speaking": True})

            response = ""
            try:
                # TTS worker processes sentences in order while the LLM is still generating.
                tts_queue: asyncio.Queue[str | None] = asyncio.Queue()

                async def _tts_worker() -> None:
                    while True:
                        sentence = await tts_queue.get()
                        if sentence is None:
                            break
                        if self._voice:
                            await self._voice.speak(sentence)

                worker = asyncio.create_task(_tts_worker()) if (tts and self._voice) else None

                try:
                    sentence_buf = ""
                    seen_len = 0

                    async with get_orchestrator().run_stream(prompt, deps=self._deps) as stream:
                        async for partial in stream.stream_output(debounce_by=0.05):
                            current = (getattr(partial, "response", None) or "")
                            delta = current[seen_len:]
                            seen_len = len(current)
                            if delta:
                                sentence_buf += delta
                                m = _SENT_RE.search(sentence_buf)
                                while m:
                                    sent = sentence_buf[: m.start() + 1].strip()
                                    sentence_buf = sentence_buf[m.end():]
                                    if sent and worker is not None:
                                        await tts_queue.put(sent)
                                    m = _SENT_RE.search(sentence_buf)

                        output = await stream.get_output()
                        response = output.response

                    # Flush remainder or fall back if streaming gave no deltas.
                    remaining = sentence_buf.strip() or (response if not seen_len else "")
                    if remaining and worker is not None:
                        for sent in _split_sentences(remaining):
                            await tts_queue.put(sent)

                finally:
                    if worker is not None:
                        await tts_queue.put(None)
                        await worker

                self._turns.append({"user": prompt, "assistant": response})
                logger.info("[désir] %s", response)
                await self.send_json({"type": "transcript", "role": "assistant", "text": response})
                await self.send_json({"type": "completed", "message": "Ready for your next instruction."})
            except SessionFrozenError as exc:
                await self.send_json({"type": "error", "message": str(exc)})
            except Exception as exc:  # noqa: BLE001
                logger.exception("orchestrator run failed")
                await self.send_json({"type": "error", "message": str(exc)})
            finally:
                await self.send_json({"type": "state", "speaking": False})
                await self.push_ledger_tail()

    async def _compact_session(self) -> None:
        if not self._turns or self._deps is None:
            return
        try:
            from datetime import datetime, timezone
            from config import settings
            from memory.graph import get_graph_knowledge
            from openai import AsyncOpenAI

            transcript = "\n".join(
                f"User: {t['user']}\nAssistant: {t['assistant']}" for t in self._turns
            )
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a memory assistant. Given a conversation transcript, "
                            "return a JSON object with:\n"
                            '  "topic": short topic title (5 words max)\n'
                            '  "summary": concise summary of what was discussed, decided, or done\n'
                            '  "metadata": key facts, preferences, or action items as bullet points\n'
                            "Be factual and brief."
                        ),
                    },
                    {"role": "user", "content": transcript},
                ],
                response_format={"type": "json_object"},
            )
            import json
            data = json.loads(resp.choices[0].message.content)
            topic = data.get("topic", "Session")
            summary = data.get("summary", "")
            metadata = data.get("metadata", "")
            content = f"{summary}\n\nMetadata:\n{metadata}\n\nDate: {date_str}"
            label = f"{topic} — {date_str}"

            graph = get_graph_knowledge()
            await graph.upsert_node(
                user_id=self._user_id,
                label=label,
                content=content,
                node_type="session",
            )
            logger.info("[session] compacted to graph node: %s", label)
        except Exception:
            logger.exception("[session] compact failed — session not saved")

    async def push_ledger_tail(self, limit: int = 10) -> None:
        if self._deps is None:
            return
        entries = await self._deps.ledger.history(limit=limit)
        if not entries:
            return
        await self.send_json(
            {
                "type": "ledger_update",
                "entries": [serialize_ledger_entry(e) for e in entries],
            }
        )
