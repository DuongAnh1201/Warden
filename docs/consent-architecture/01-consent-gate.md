# Phase 1 — The Consent Gate (Zero-Trust Middleware)

The LLM cannot be trusted to self-police. The Consent Gate is a **hard-coded middleware
layer** that sits between the Pydantic AI orchestrator and the external API clients
(Resend, Google Drive, macOS Calendar, Fetch.ai). It is the only path to a side effect.

## 1. Intent serialization — the pause

When the orchestrator decides an action is necessary it **does not call the tool**. It
emits a strict, typed `ProposedAction`. The tool functions are not even in scope for the
LLM to call directly — it can only produce intent.

```python
from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field

class ActionType(str, Enum):
    SEND_EMAIL       = "send_email"
    CREATE_EVENT     = "create_event"
    SHARE_DRIVE_FILE = "share_drive_file"
    SAVE_DRAFT       = "save_draft"
    SET_REMINDER     = "set_reminder"
    NEGOTIATE_AGENT  = "negotiate_agent"
    # ... every supported action is enumerated; unknown == default-deny

class ConsentTier(int, Enum):
    SILENT     = 0   # auto-execute, passive notice, revertible (see 04-trust-tiers.md)
    SOFT       = 1   # non-blocking notice + short undo window
    HARD_STOP  = 2   # blocking verbal approval required (the default)

class ProposedAction(BaseModel):
    action_id: str                       # uuid4
    type: ActionType
    target: dict                         # typed, validated args for the tool
    summary: str                         # human-readable, read back by voice
    tier: ConsentTier                    # assigned by the static classifier, NOT the LLM
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
```

> **Critical:** `tier` is assigned by a **static, code-defined classifier** (an allowlist
> keyed by `ActionType` + context), never inferred by the model at runtime. The LLM
> proposes; the gate classifies. This is the "static inspection of the agent's pathways
> before execution" guarantee.

## 2. Redis state management

The `ProposedAction` is hashed and pushed to a Redis hash map with a strict **TTL of 300s**
and status `PENDING_CONSENT`.

```
HSET  action:{action_id}  status PENDING_CONSENT  tier 2  payload {json}
EXPIRE action:{action_id}  300
```

State machine:

```
PENDING_CONSENT ──(approve)──► CONSENT_CONFIRMED ──► EXECUTING ──► EXECUTED
       │                                                  │
       ├──(TTL expires)──► EXPIRED                         └──(API error)──► EXECUTION_FAILED
       └──(ambiguous/conflict)──► REVISE_REQUESTED
```

Every transition is fail-closed: an action only leaves `PENDING_CONSENT` toward execution
through `CONSENT_CONFIRMED`, which requires a token.

## 3. The Consent Token

When the user gives spoken approval via Deepgram, the backend mints a token by hashing the
approval **timestamp + action_id + transcription text** (plus a server-side secret so the
token cannot be forged client-side). The token is appended to the **Redis Stream** — the
append-only Consent Ledger.

```python
import hashlib, hmac, os

def mint_consent_token(action_id: str, transcript: str, ts: str) -> str:
    msg = f"{ts}|{action_id}|{transcript}".encode()
    return hmac.new(os.environ["CONSENT_SECRET"].encode(), msg, hashlib.sha256).hexdigest()
```

```
XADD consent_ledger * action_id {id} token {hex} transcript "{...}" ts {iso} tier {n} decision approved
```

The ledger is append-only and is the artifact the Phase 3 evaluator audits.

## 4. The execution lock

The actual API wrappers require a token and verify it against the ledger before doing
anything. The check lives **in the wrapper**, so even if the orchestrator hallucinates and
calls the tool directly, it fails closed.

```python
def execute_send_email(payload: dict, consent_token: str | None):
    record = ledger.lookup(payload["action_id"])
    if consent_token is None or not record or not constant_time_eq(record.token, consent_token):
        raise ConsentError("BLOCKED: missing/invalid Consent_Token")   # fail closed
    if record.status != "CONSENT_CONFIRMED":
        raise ConsentError("BLOCKED: action not in confirmed state")
    return resend_client.send(**payload["target"])                     # only path to effect
```

This is the line MoneyPenny guards: a token is the *only* thing that turns intent into a
real-world effect. How that token is obtained — a hard verbal "yes" vs. an auto-issued
silent token with a registered rollback — is the subject of
[`04-trust-tiers.md`](./04-trust-tiers.md).

---

## Implementation status (what is wired today)

The token + execution lock from §3–§4 are implemented. The mechanism is adapted to the
existing orchestrator while preserving the rule *no token, no effect*:

| Spec concept | Implemented as |
|---|---|
| `ProposedAction` (the pause) | `ActionRequest` in `schemas/consent.py`, raised by every gated tool |
| The single funnel | `gate()` in `ai/agents/consent.py` — records request → decision → outcome |
| `Consent_Token` (HMAC of `ts \| action_id \| transcript`) | `ai/agents/consent_token.py` (`mint_consent_token`), minted on approval and appended to the ledger via `ActionDecision.consent_token` |
| The execution lock in the wrapper | `tools/execution_lock.py` (`require_consent`), called at the top of every side-effecting tool (`send_user_email`, calendar create/update/delete, iMessage/call, knowledge create/update/add_context) |
| TTL / expiry | `CONSENT_TTL_SECONDS = 300`; the active grant carries `expires_at` and `require_consent` rejects expired grants |
| Default-deny on bypass | A tool invoked outside the gate has no active `ConsentGrant` → `require_consent` raises `ConsentError` and nothing fires |

**Mechanism note.** Rather than threading a token argument through every tool, the gate
opens a process-local `consent_scope` (a `contextvars.ContextVar`) carrying the grant; the
grant propagates into worker threads via `asyncio.to_thread`. The grant is **single-use**
and **scoped to one `action_type`**, so an approval for `calendar.create` cannot be reused
to `email.send`. The HMAC `Consent_Token` is still minted and written to the ledger as the
auditable proof of consent.

**Not yet implemented (still aspirational here):** the explicit
`PENDING_CONSENT → CONSENT_CONFIRMED` Redis status machine, static Trust Tiers
([`04-trust-tiers.md`](./04-trust-tiers.md)), and the Phoenix bypass evaluator / kill
switch ([`03-observability-and-ledger.md`](./03-observability-and-ledger.md)).
