# Phase 2 — Fallback & Edge-Condition Matrix

Asynchronous agents, distributed networks, and human latency all mean things will drop.
The rule is uniform: **MoneyPenny fails closed.** When in doubt, nothing happens.

| Threat / Edge Case | Trigger Condition | System Action | Fallback (what MoneyPenny says/does) |
|---|---|---|---|
| **User timeout** | Redis TTL (300s) on a `PENDING_CONSENT` action expires before the user answers. | State → `EXPIRED`. Action permanently dropped. No token is ever minted. | On next interaction: *"I canceled the email to Priya since we timed out."* |
| **Ambiguous voice input** | Deepgram confidence `< 0.85`, or conflicting speech (*"Yeah, wait, no, cancel"*). | Fail closed. State → `REVISE_REQUESTED`. | Binary override prompt: *"I didn't catch a clear yes or no. Should I send this or cancel?"* |
| **Agent network desync** | In a Fetch.ai p2p negotiation, your agent approves but Sam's agent goes offline / times out. | Distributed **Two-Phase Commit (2PC)**. Neither side writes locally until both broadcast `CONSENT_CONFIRMED`. | On peer timeout: roll back the prepared state and report *"Sam's side timed out. Should I try again later?"* |
| **Orchestrator hallucination** | Pydantic AI skips `ProposedAction` and calls a sensitive tool directly. | The hard-coded execution lock blocks it — no `Consent_Token`. | Phoenix flags a critical anomaly (tool call with no preceding consent span). Session terminated and restarted. |
| **API failure post-consent** | User said "Yes," but Resend / Drive returns 500. | Token is consumed; action fails. State → `EXECUTION_FAILED`. | Verbal interrupt: *"I tried to send that, but the email server is down. I've saved the draft. Let me know when to retry."* |

## Two-Phase Commit for agent-to-agent actions

Cross-agent actions (scheduling between two MoneyPenny users) are **never silent** and
always require both humans. The 2PC sequence:

```
PREPARE   both agents lock the proposed slot locally, status = PREPARED (not written)
VOTE      each agent collects its owner's verbal consent → mints a local Consent_Token
COMMIT    only when BOTH tokens exist do both broadcast CONSENT_CONFIRMED and write
ABORT     any timeout / "no" / token-miss → both roll back PREPARED state, write nothing
```

The invariant: **a calendar is written only if both owners approved.** A one-sided
approval is indistinguishable from "no deal" until the peer confirms.

## Edge-case defaults (the fail-closed checklist)

- **Unknown action type** → default-deny, escalate to Tier 2 (hard stop).
- **Confidence below threshold** → never auto-execute, never Tier 0. Drops to
  `REVISE_REQUESTED`.
- **Notification delivery failure** for a silent (Tier 0) action → abort before execution;
  if the user can't be told, the action can't be silent.
- **Revert window cannot be guaranteed** (no compensating action available) → action is
  not Tier 0 by definition; escalate. See [`04-trust-tiers.md`](./04-trust-tiers.md).
- **Token reuse / replay** → tokens are single-use, bound to one `action_id`, and consumed
  on execution.
