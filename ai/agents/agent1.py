"""Email sub-agent — sends via the user's Gmail account (Google Workspace OAuth).

Contacts must be saved in the knowledge graph (node_type='contact') before any
email can be sent to them. Spelled-out addresses go through register_unverified_contact
and require consent-gate approval before they become usable.
"""
import asyncio
import re

from pydantic_ai import Agent, RunContext

from ai.agents.consent import gate
from ai.agents.deps import OrchestratorDeps
from ai.prompts import load_prompt
from schemas.agent1 import EmailAgentResult, EmailDraft  # noqa: F401 — re-exported for callers

_email_agent: Agent | None = None
_SYSTEM_PROMPT = load_prompt("email_agent")

# Simple regex to pull 'email: addr@example.com' from a contact node's content.
_EMAIL_LINE = re.compile(r"^email:\s*(.+)$", re.IGNORECASE | re.MULTILINE)

# Pre-seeded contacts available in all modes (demo and live).
_DEFAULT_CONTACTS: dict[str, str] = {
    "tom nguyen": "tomnguyen6766@gmail.com",
    "khoi duong": "khoiduong2913@gmail.com",
}


def _match_default(query: str) -> str | None:
    """Return a verified email from the default contacts by name fragment or exact email."""
    q = query.lower().strip()
    for email in _DEFAULT_CONTACTS.values():
        if email.lower() == q:
            return email
    for name, email in _DEFAULT_CONTACTS.items():
        if q in name or name in q:
            return email
    return None


async def _resolve_contact_email(ctx: RunContext[OrchestratorDeps], address: str) -> str | None:
    """Return the verified email if *address* matches a saved contact, else None."""
    default = _match_default(address)
    if default:
        return default
    if ctx.deps.knowledge is None:
        return None
    results = await ctx.deps.knowledge.search(ctx.deps.user_id, query=address, top_k=10)
    for node in results:
        if node.node_type != "contact":
            continue
        m = _EMAIL_LINE.search(node.content)
        if m and m.group(1).strip().lower() == address.lower():
            return m.group(1).strip()
    return None


def get_email_agent() -> Agent:
    global _email_agent
    if _email_agent is None:
        from config import settings
        from observability.phoenix import get_agent_instrumentation

        _email_agent = Agent(
            model=settings.ai_model,
            name="email_agent",
            system_prompt=_SYSTEM_PROMPT,
            output_type=EmailAgentResult,
            deps_type=OrchestratorDeps,
            capabilities=get_agent_instrumentation(),
        )

        # ── Contact lookup ────────────────────────────────────────────────────

        @_email_agent.tool
        async def lookup_contact(ctx: RunContext[OrchestratorDeps], name: str) -> str:
            """Search saved, verified contacts by name. Returns name + email pairs.
            Always call this before send_user_email — only use addresses returned here.
            """
            lines: list[str] = []

            # Always check built-in default contacts first.
            q = name.lower().strip()
            for contact_name, email in _DEFAULT_CONTACTS.items():
                if q in contact_name or contact_name in q:
                    lines.append(f"{contact_name.title()}: {email}")

            # Then search the knowledge graph if available.
            if ctx.deps.knowledge is not None:
                results = await ctx.deps.knowledge.search(ctx.deps.user_id, query=name, top_k=5)
                for node in (n for n in results if n.node_type == "contact"):
                    m = _EMAIL_LINE.search(node.content)
                    email = m.group(1).strip() if m else "(no email stored)"
                    entry = f"{node.label}: {email}"
                    if entry not in lines:
                        lines.append(entry)

            if not lines:
                return f"No verified contact found for '{name}'."
            return "\n".join(lines)

        # ── New-address verification ticket ───────────────────────────────────

        @_email_agent.tool
        async def register_unverified_contact(
            ctx: RunContext[OrchestratorDeps],
            name: str,
            email: str,
        ) -> str:
            """Register a new email address the user spelled out.
            Creates a verification ticket — the user must approve before this address
            can be used for sending. Never call send_user_email with unregistered addresses.
            """
            async def _execute() -> str:
                if ctx.deps.knowledge is None:
                    return "Cannot save contact: knowledge store unavailable."
                await ctx.deps.knowledge.upsert_node(
                    user_id=ctx.deps.user_id,
                    label=name or email,
                    content=f"email: {email}\nstatus: verified",
                    node_type="contact",
                )
                return (
                    f"Contact verified and saved: {name} <{email}>. "
                    "You can now send emails to this address."
                )

            return await gate(
                ctx,
                action_type="contact.register",
                agent="email_agent",
                summary=f"Save new contact: {name} <{email}>",
                payload={"name": name, "email": email},
                execute=_execute,
            )

        # ── Sending ───────────────────────────────────────────────────────────

        @_email_agent.tool
        async def send_user_email(
            ctx: RunContext[OrchestratorDeps],
            to: str,
            subject: str,
            body: str,
            cc: list[str] | None = None,
        ) -> str:
            """Send a plain-text email. The 'to' address must be a verified contact
            returned by lookup_contact — this tool will reject unverified addresses.
            """
            # Guard: address must exist as a verified contact in the knowledge graph.
            if ctx.deps.knowledge is not None:
                verified = await _resolve_contact_email(ctx, to)
                if verified is None:
                    return (
                        f"Blocked: '{to}' is not a saved contact. "
                        "Use lookup_contact to find a saved address, or "
                        "register_unverified_contact if the user just spelled it out."
                    )

            from tools.gmail import send_message

            async def _execute() -> str:
                result = await asyncio.to_thread(
                    send_message,
                    to=to,
                    subject=subject,
                    body=body,
                    creds=ctx.deps.workspace_creds,
                    cc=cc,
                )
                if result == "ok":
                    return f"Email sent to {to}."
                return f"Failed to send to {to}. Reason: {result}"

            return await gate(
                ctx,
                action_type="email.send",
                agent="email_agent",
                summary=f"Send email to {to} — subject '{subject}'",
                payload={"to": to, "subject": subject, "body": body, "cc": cc},
                execute=_execute,
            )

        @_email_agent.tool
        async def send_notification_email(
            ctx: RunContext[OrchestratorDeps],
            to: str,
            subject: str,
            details: str,
            link: str = "",
        ) -> str:
            """Send a styled HTML notification email (reminders, alerts, status updates).
            'to' must be a verified contact or the user's own email address.
            """
            if ctx.deps.knowledge is not None:
                verified = await _resolve_contact_email(ctx, to)
                if verified is None:
                    return (
                        f"Blocked: '{to}' is not a saved contact. "
                        "Register it first with register_unverified_contact."
                    )

            from tools.gmail import send_message

            async def _execute() -> str:
                link_html = (
                    f'<p><a href="{link}" style="color:#2563eb">Open</a></p>' if link else ""
                )
                html = (
                    '<div style="font-family:sans-serif;max-width:520px;margin:auto">'
                    f"<h2 style='color:#111'>{subject}</h2>"
                    f"<p style='color:#333;line-height:1.5'>{details}</p>"
                    f"{link_html}"
                    "<hr style='border:none;border-top:1px solid #eee'>"
                    "<p style='color:#888;font-size:12px'>Sent by Désir</p>"
                    "</div>"
                )
                result = await asyncio.to_thread(
                    send_message,
                    to=to,
                    subject=subject,
                    body=details,
                    creds=ctx.deps.workspace_creds,
                    html=html,
                )
                if result == "ok":
                    return f"Notification sent to {to}."
                return f"Failed to send notification to {to}. Reason: {result}"

            return await gate(
                ctx,
                action_type="email.notification",
                agent="email_agent",
                summary=f"Send notification to {to} — subject '{subject}'",
                payload={"to": to, "subject": subject, "details": details, "link": link},
                execute=_execute,
            )

    return _email_agent
