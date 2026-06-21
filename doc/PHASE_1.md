# Phase 1 — The Consent Gate, Generalized + Ledger

> Goal: **every consequential action pauses for explicit approval, and every request + decision + outcome is recorded in an auditable ledger.** This turns the email-only `request_email_approval` hook into one mechanism shared by all agents, and adds the persistence that later phases (Phase 5 safety evals, Phase 6 cross-agent commitments) verify against.

This is the phase that makes the README's central promise — *"agents negotiate, humans decide"* — a structural property of the code rather than a per-agent habit.

---

## 1. Where we are today

The consent idea already exists, but only for email and only in-memory:

- [ai/agents/deps.py](../ai/agents/deps.py) — `OrchestratorDeps.request_email_approval: Any` is an optional async callback.
- [ai/agents/agent1.py](../ai/agents/agent1.py) — each email tool has two branches: if the callback is set, build an `EmailDraft` and `await ctx.deps.request_email_approval(draft)`; otherwise send directly.
- Other consequential tools have **no gate at all**: calendar create/update/delete ([agent2.py](../ai/agents/agent2.py)), iMessage/call ([agent4.py](../ai/agents/agent4.py)), and knowledge create/update/delete ([agent5.py](../ai/agents/agent5.py)) all act immediately.
- Nothing is persisted. The callback returns a string and the event is gone.

**Problems to fix in Phase 1**
1. The gate is duplicated per-tool and only covers email.
2. "No callback set" silently means "act without asking" — the unsafe default.
3. There is no record of what was requested, what the user decided, or what happened.

---

## 2. What "consequential" means (the gate's scope)

| Agent | Tool | Gated? | Why |
|---|---|---|---|
| Email | `send_user_email`, `send_notification_email` | **Yes** | Sends to the outside world |
| Email | `register_domain` | **Yes** | Account/DNS change |
| Calendar | `create_calendar_event`, `update_calendar_event`, `delete_calendar_event` | **Yes** | Mutates the calendar |
| Calendar | `list_calendars`, `check_freebusy` | No | Read-only |
| Communication | `send_imessage`, `make_call` | **Yes** | Contacts a person |
| Communication | `search_contact` | No | Read-only |
| Knowledge | `create_new_file`, `update_file`, `add_context` | **Yes** (lightweight) | Writes user data |
| Knowledge | `read_file` | No | Read-only |
| Search | `search_web` | No | Read-only |

Rule of thumb encoded in the design: **a tool is gated if it writes, sends, contacts, or spends.** Read-only tools never gate.

---

## 3. New schemas (`schemas/consent.py`)

Following the centralization rule, all new models go in `schemas/`. One new file:

```python
# schemas/consent.py
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field

ActionType = Literal[
    "email.send", "email.notification", "email.register_domain",
    "calendar.create", "calendar.update", "calendar.delete",
    "comms.imessage", "comms.call",
    "knowledge.create", "knowledge.update", "knowledge.add_context",
]
Decision = Literal["approve", "cancel", "revise"]
Outcome  = Literal["executed", "failed", "cancelled", "pending"]


class ActionRequest(BaseModel):
    """A consequential action awaiting the user's decision."""
    action_id: str = Field(default_factory=lambda: uuid4().hex)
    action_type: ActionType
    agent: str                      # which sub-agent raised it
    summary: str                    # one-line, voice-friendly ("Send email to Priya: 'Deck is ready'")
    payload: dict[str, Any]         # the concrete args needed to execute
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActionDecision(BaseModel):
    action_id: str
    decision: Decision
    revision_note: str = ""         # set when decision == "revise"
    decided_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LedgerEntry(BaseModel):
    """One fully-resolved row in the consent ledger."""
    request: ActionRequest
    decision: ActionDecision | None = None
    outcome: Outcome = "pending"
    result_message: str = ""
    resolved_at: datetime | None = None
```

`EmailDraft` (now in [schemas/agent1.py](../schemas/agent1.py)) becomes a thin convenience that maps onto an `ActionRequest` — or is retired in favour of `ActionRequest` directly. Keep it for one release for backward compatibility, then remove.

---

## 4. The gate function (`ai/agents/consent.py`)

A single coroutine every gated tool funnels through. It owns the request→decision→execute→record lifecycle so no tool reimplements it.

```python
# ai/agents/consent.py  (sketch)
async def gate(
    ctx,                      # RunContext[OrchestratorDeps]
    action_type, agent, summary, payload,
    execute,                  # async () -> str  (the real side effect)
) -> str:
    req = ActionRequest(action_type=action_type, agent=agent,
                        summary=summary, payload=payload)
    ledger = ctx.deps.ledger
    await ledger.record_request(req)

    approver = ctx.deps.request_approval
    if approver is None:
        # Safe default: do NOT act. (auto_approve flag flips this for tests/demo.)
        decision = _auto_decision(ctx.deps, req)
    else:
        decision = await approver(req)
    await ledger.record_decision(decision)

    if decision.decision == "cancel":
        await ledger.record_outcome(req.action_id, "cancelled", "User cancelled.")
        return "Cancelled — nothing was done."
    if decision.decision == "revise":
        await ledger.record_outcome(req.action_id, "cancelled", "User asked to revise.")
        return f"Revision requested: {decision.revision_note}. Adjust and re-propose."

    try:
        result = await execute()
        await ledger.record_outcome(req.action_id, "executed", result)
        return result
    except Exception as e:                       # noqa: BLE001
        await ledger.record_outcome(req.action_id, "failed", str(e))
        return f"Action failed: {e}. Do not retry."
```

Key properties:
- **Records before and after.** A request is in the ledger even if the process dies mid-approval — that's what Phase 5 reconciles against.
- **Approval default is deny.** `_auto_decision` returns `approve` only when `deps.auto_approve` is explicitly set (CLI smoke tests, hosted demo persona); otherwise `cancel`. No silent sends.
- **Revise** returns guidance text the agent can act on (re-draft and call the tool again), matching the README's "approve / cancel / revise".

---

## 5. The ledger (`tools/ledger.py`)

An append-only log with two interchangeable backends behind one interface.

```python
class ConsentLedger(Protocol):
    async def record_request(self, req: ActionRequest) -> None: ...
    async def record_decision(self, d: ActionDecision) -> None: ...
    async def record_outcome(self, action_id: str, outcome: Outcome, message: str) -> None: ...
    async def history(self, limit: int = 50) -> list[LedgerEntry]: ...
```

- **`RedisLedger`** (production) — appends each event with `XADD consent:ledger * ...` (Redis Streams, per the README architecture). Streams give ordering, time, and replay for the safety evals.
- **`FileLedger`** (local/demo fallback) — appends JSON lines to `./.consent/ledger.jsonl` (alongside the existing `.knowledge/` convention; both are gitignored).

Selection mirrors the tools' `DEMO_MODE` pattern: use `RedisLedger` when `REDIS_URL` is set, else `FileLedger`. A factory `get_ledger()` returns the singleton.

> Redis itself (memory + vector recall) is fully built in **Phase 4**. Phase 1 only needs the Streams append path; the `FileLedger` keeps everything runnable until then.

---

## 6. Changes to `OrchestratorDeps`

```python
# ai/agents/deps.py
request_approval: Callable[[ActionRequest], Awaitable[ActionDecision]] | None = None
ledger: ConsentLedger = field(default_factory=get_ledger)
auto_approve: bool = False     # CLI/demo only — bypasses the human, still logs
```

`request_email_approval` is **removed** and its two call sites in [agent1.py](../ai/agents/agent1.py) move to `gate(...)`. (Grep confirms those are the only two references.)

---

## 7. Per-tool wiring (the mechanical part)

Each gated tool collapses its logic into a `gate(...)` call. Email loses its dual-branch entirely. Example for `send_user_email`:

```python
@_email_agent.tool
async def send_user_email(ctx, to, subject, body) -> str:
    async def _execute() -> str:
        from config import settings
        from tools.sending_email import send_user_email as _send
        result = await asyncio.to_thread(_send, recipient=to, subject=subject, body=body,
                                        api_key=settings.resend_api_key,
                                        from_address=settings.resend_from)
        return f"Email sent to {to}." if result == "ok" else f"Failed: {result}"

    return await gate(ctx, "email.send", "email_agent",
                    summary=f"Send email to {to} — subject '{subject}'",
                    payload={"to": to, "subject": subject, "body": body},
                    execute=_execute)
```

Apply the same shape to:
- [agent2.py](../ai/agents/agent2.py): `create_calendar_event`, `update_calendar_event`, `delete_calendar_event`
- [agent4.py](../ai/agents/agent4.py): `send_imessage`, `make_call`
- [agent5.py](../ai/agents/agent5.py): `create_new_file`, `update_file`, `add_context`

Read-only tools are untouched.

---

## 8. The interim approver (until Phase 2 has a UI)

There is no server/voice yet, so Phase 1 ships a **console approver** so the gate is demonstrable end-to-end:

- In [run_text.py](../run_text.py), set `deps.request_approval` to a coroutine that prints the `summary` and reads `approve / cancel / revise (note)` from stdin.
- Add `--yes` to set `deps.auto_approve = True` for non-interactive smoke runs (still writes the ledger).

Phase 2 replaces this console approver with a WebSocket push to the browser's review card; Phase 3 replaces stdin with the spoken "send it / cancel / change the time." **The gate signature does not change** across those phases — only the approver implementation does.

---

## 9. Files touched

| File | Change |
|---|---|
| `schemas/consent.py` | **new** — `ActionRequest`, `ActionDecision`, `LedgerEntry`, type aliases |
| `tools/ledger.py` | **new** — `ConsentLedger`, `RedisLedger`, `FileLedger`, `get_ledger()` |
| `ai/agents/consent.py` | **new** — the `gate()` coroutine + `_auto_decision` |
| `ai/agents/deps.py` | add `request_approval`, `ledger`, `auto_approve`; remove `request_email_approval` |
| `ai/agents/agent1.py` | route both email tools (+ `register_domain`) through `gate()` |
| `ai/agents/agent2.py` | gate create/update/delete |
| `ai/agents/agent4.py` | gate iMessage/call |
| `ai/agents/agent5.py` | gate create/update/add_context |
| `run_text.py` | console approver + `--yes` flag; print ledger tail after a run |
| `config.py` | add `redis_url` setting (optional) |

---

## 10. Acceptance criteria (definition of done)

1. **Nothing consequential fires without a decision.** With no approver and `auto_approve=False`, every gated tool returns "Cancelled" and performs no side effect.
2. **Approve path works end-to-end.** `uv run python run_text.py "Email priya@example.com the deck is ready"` prompts at the console; approving sends (demo-simulated) and prints a confirmation.
3. **Revise path works.** Choosing "revise" with a note returns guidance and the agent can re-propose without sending.
4. **Ledger is complete and ordered.** After any run, `.consent/ledger.jsonl` (or the Redis stream) contains a request, a decision, and an outcome for every gated action — and *no* outcome without a matching approval.
5. **Read-only tools never appear in the ledger** (search, free/busy, contact lookup, knowledge read).
6. **Smoke check still green:** `run_text.py --check` builds all agents.

A tiny reconciliation script (`scripts/audit_ledger.py`, optional here, formalized in Phase 5) should report zero "executed outcomes without an approve decision."

---

## 11. Risks & decisions to confirm

- **Default policy = deny.** Confirmed direction: an unconfigured assistant must not act. The only bypass is the explicit `auto_approve` demo flag.
- **Granularity of `revise`.** v1 treats revise as "cancel + return note"; the agent re-proposes a fresh action. A future version could carry an editable draft through the gate.
- **Ledger PII.** Email bodies / message text land in the ledger. For the hosted demo, store summaries + hashes rather than full bodies, or scope the file to the session. Decide before any shared deployment.
- **Redis now or later?** Recommended: build `FileLedger` in Phase 1, add `RedisLedger` opportunistically; don't block Phase 1 on standing up Redis.
```
