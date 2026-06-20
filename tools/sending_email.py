"""Email sending via Resend.

All functions are synchronous; the agents call them through ``asyncio.to_thread``.
In :data:`DEMO_MODE` (or when no API key is configured) nothing is sent — the
call is logged and reported as successful so the full flow stays demoable.
"""
from __future__ import annotations

from schemas.agent1 import NotificationEmailRequest
from tools import DEMO_MODE
from tools.execution_lock import require_consent


def _simulate(kind: str, recipient: str, subject: str) -> str:
    print(f"[DEMO] {kind} email -> {recipient} | subject: {subject!r} (not actually sent)")
    return "ok"


def send_user_email(
    recipient: str,
    subject: str,
    body: str,
    api_key: str = "",
    from_address: str = "Desir <onboarding@resend.dev>",
) -> str:
    """Send a plain-text email. Returns ``"ok"`` or an error message string."""
    require_consent("email.send")
    if DEMO_MODE or not api_key:
        return _simulate("user", recipient, subject)

    import resend

    resend.api_key = api_key
    try:
        resend.Emails.send(
            {
                "from": from_address,
                "to": [recipient],
                "subject": subject,
                "text": body,
            }
        )
        return "ok"
    except Exception as e:  # noqa: BLE001 - surface any provider error to the agent
        return f"resend error: {e}"


def _render_notification_html(n: NotificationEmailRequest) -> str:
    link_html = (
        f'<p><a href="{n.link}" style="color:#2563eb">Open</a></p>' if n.link else ""
    )
    return (
        '<div style="font-family:sans-serif;max-width:520px;margin:auto">'
        f"<h2 style='color:#111'>{n.subject}</h2>"
        f"<p style='color:#333;line-height:1.5'>{n.details}</p>"
        f"{link_html}"
        f"<hr style='border:none;border-top:1px solid #eee'>"
        f"<p style='color:#888;font-size:12px'>Sent by {n.sender_name}</p>"
        "</div>"
    )


def send_notification_email(n: NotificationEmailRequest) -> str:
    """Send a styled HTML notification. Returns ``"ok"`` or an error string."""
    require_consent("email.notification")
    if DEMO_MODE or not n.api_key:
        return _simulate("notification", n.recipient, n.subject)

    import resend

    resend.api_key = n.api_key
    payload = {
        "from": n.from_address,
        "to": [n.recipient],
        "subject": n.subject,
        "html": _render_notification_html(n),
    }
    if n.scheduleAt:
        payload["scheduled_at"] = n.scheduleAt
    try:
        resend.Emails.send(payload)
        return "ok"
    except Exception as e:  # noqa: BLE001
        return f"resend error: {e}"


def add_domain(domain_name: str):
    """Register a sending domain with Resend and return the created domain object.

    Raises on failure so the agent can report the reason.
    """
    require_consent("email.register_domain")
    if DEMO_MODE:
        return {
            "id": "demo-domain-id",
            "records": [
                {"type": "TXT", "name": domain_name, "value": "demo-verification"},
                {"type": "MX", "name": domain_name, "value": "feedback-smtp.resend.dev"},
            ],
        }

    import resend

    return resend.Domains.create({"name": domain_name})
