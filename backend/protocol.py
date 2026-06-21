"""WebSocket ↔ browser message shapes for Phase 2."""
from __future__ import annotations

from typing import Any, Literal

from schemas.consent import ActionRequest, LedgerEntry

ClientMessageType = Literal[
    "session_start",
    "text",
    "audio",
    "approval_decision",
    "tool_result",
    "ping",
]

ServerMessageType = Literal[
    "state",
    "transcript",
    "tool_call",
    "approval_request",
    "approval_resolved",
    "ledger_update",
    "completed",
    "error",
    "session_ready",
    "pong",
]

ACTION_TOOL_NAMES: dict[str, str] = {
    "email.send": "send_email",
    "email.notification": "send_email",
    "calendar.create": "schedule_event",
    "calendar.update": "schedule_event",
    "calendar.delete": "schedule_event",
    "comms.imessage": "send_imessage",
    "comms.call": "make_call",
    "gmail.modify": "gmail_triage",
    "gmail.draft": "send_email",
    "gmail.trash": "gmail_triage",
    "drive.upload": "drive_write",
    "drive.create_folder": "drive_write",
    "drive.update": "drive_write",
    "drive.share": "drive_write",
    "drive.delete": "drive_write",
}


def action_to_approval_request(req: ActionRequest) -> dict[str, Any]:
    """Map a consent-gate ActionRequest to the frontend ApprovalRequest shape."""
    preview: dict[str, Any] | None = None
    if req.action_type.startswith("email.") or req.action_type == "gmail.draft":
        preview = {
            "to": str(req.payload.get("to") or req.payload.get("recipient") or ""),
            "subject": str(req.payload.get("subject", "")),
            "body": str(req.payload.get("body") or req.payload.get("details") or ""),
            "emailType": (
                "notification"
                if req.action_type == "email.notification"
                else "user_request"
            ),
            "link": req.payload.get("link"),
        }
    elif req.action_type == "agent.message":
        # Render the Agentverse hand-off as a ticket with the same preview shape
        # as an email, so the user reviews the recipient agent and message body.
        preview = {
            "to": str(req.payload.get("address", "")),
            "subject": "Agentverse message",
            "body": str(req.payload.get("message", "")),
            "emailType": "agent_message",
            "link": None,
        }

    return {
        "id": req.action_id,
        "toolName": ACTION_TOOL_NAMES.get(req.action_type, req.action_type),
        "title": req.action_type.replace(".", " ").replace("_", " ").upper(),
        "summary": req.summary,
        "detail": req.summary,
        "preview": preview,
    }


def serialize_ledger_entry(entry: LedgerEntry) -> dict[str, Any]:
    return {
        "action_id": entry.request.action_id,
        "action_type": entry.request.action_type,
        "agent": entry.request.agent,
        "summary": entry.request.summary,
        "decision": entry.decision.decision if entry.decision else None,
        "outcome": entry.outcome,
        "result_message": entry.result_message,
        "created_at": entry.request.created_at.isoformat(),
        "resolved_at": entry.resolved_at.isoformat() if entry.resolved_at else None,
    }
