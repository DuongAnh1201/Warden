"""WebSocket-backed consent approval — pushes cards and awaits client decisions."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from schemas.consent import ActionDecision, ActionRequest
from backend.protocol import action_to_approval_request

logger = logging.getLogger(__name__)

APPROVAL_TIMEOUT_SECONDS = 300

SendFn = Callable[[dict], Awaitable[None]]


class WebSocketApprover:
    """Present ActionRequests to the browser and block until the user decides."""

    def __init__(self, send_json: SendFn) -> None:
        self._send = send_json
        self._pending: dict[str, asyncio.Future[ActionDecision]] = {}

    async def __call__(self, req: ActionRequest) -> ActionDecision:
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[ActionDecision] = loop.create_future()
        self._pending[req.action_id] = fut

        approval = action_to_approval_request(req)
        await self._send({"type": "approval_request", "request": approval})
        await self._send(
            {
                "type": "tool_call",
                "call_id": req.action_id,
                "name": approval["toolName"],
                "args": req.payload,
            }
        )

        try:
            decision = await asyncio.wait_for(fut, timeout=APPROVAL_TIMEOUT_SECONDS)
        except TimeoutError:
            logger.info("approval timed out for action_id=%s", req.action_id)
            decision = ActionDecision(action_id=req.action_id, decision="cancel")
        finally:
            self._pending.pop(req.action_id, None)

        resolved = "approved" if decision.decision == "approve" else "cancelled"
        await self._send(
            {
                "type": "approval_resolved",
                "request_id": req.action_id,
                "decision": resolved,
            }
        )
        return decision

    def has_pending(self) -> bool:
        """True while at least one approval is awaiting a decision."""
        return any(not f.done() for f in self._pending.values())

    def latest_pending_id(self) -> str | None:
        """action_id of the most recent un-resolved approval, if any."""
        for action_id, fut in reversed(list(self._pending.items())):
            if not fut.done():
                return action_id
        return None

    def resolve(
        self,
        action_id: str,
        decision: str,
        *,
        revision_note: str = "",
    ) -> bool:
        fut = self._pending.get(action_id)
        if fut is None or fut.done():
            return False

        normalized = decision.strip().lower()
        if normalized in ("approve", "approved", "yes", "send it"):
            fut.set_result(ActionDecision(action_id=action_id, decision="approve"))
            return True
        if normalized in ("revise", "revise_request"):
            fut.set_result(
                ActionDecision(
                    action_id=action_id,
                    decision="revise",
                    revision_note=revision_note,
                )
            )
            return True
        fut.set_result(ActionDecision(action_id=action_id, decision="cancel"))
        return True

    def cancel_all(self) -> None:
        for action_id, fut in list(self._pending.items()):
            if not fut.done():
                fut.set_result(ActionDecision(action_id=action_id, decision="cancel"))
        self._pending.clear()
