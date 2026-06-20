# Phase 3 — Observability & The Consent Ledger (Arize Phoenix)

Trust is only as good as its auditability. The Consent Ledger is not just a log — it is
**continuously evaluated** against live traces. If the evaluator and the ledger ever
disagree, the system assumes compromise and fails closed.

## Execution tracing

Every interaction is wrapped in an Arize Phoenix trace. A healthy trace for a real-world
(Tier 2) action looks exactly like this:

```
[Intent_Generated] → [Gate_Paused] → [Voice_Approval] → [Ledger_Appended] → [Tool_Executed]
```

Each span carries `action_id`, `tier`, and (for the consent spans) a reference to the
ledger entry, so a trace can be joined back to the append-only Redis Stream.

## The tier-aware span contract

Silent actions are **not exempt** from the ledger — they produce a different but equally
auditable span sequence. The single rule the evaluator enforces is unchanged:

> **Every `[Tool_Executed]` span MUST be immediately preceded, in the same trace, by a
> valid `[Ledger_Appended]` span whose token verifies against the Redis ledger.**

| Tier | Required span sequence before `[Tool_Executed]` |
|---|---|
| 2 — Hard stop | `[Intent_Generated] → [Gate_Paused] → [Voice_Approval] → [Ledger_Appended]` |
| 1 — Soft confirm | `[Intent_Generated] → [Tier_Classified:1] → [Notice_Delivered] → [Ledger_Appended]` |
| 0 — Silent | `[Intent_Generated] → [Tier_Classified:0] → [Auto_Consent_Issued] → [Rollback_Registered] → [Ledger_Appended]` |

Because `[Ledger_Appended] → [Tool_Executed]` holds for **all three tiers**, the
bypass evaluator below needs no special-casing for silent actions — which is exactly the
property that makes silent execution safe to allow.

## Automated evals (self-checking)

A continuous evaluator queries Phoenix traces asynchronously and looks for the one thing
that must never happen:

```python
def detect_consent_bypass(trace) -> bool:
    for span in trace.spans:
        if span.name == "Tool_Executed":
            prev = trace.preceding(span)                       # immediate predecessor
            if prev is None or prev.name != "Ledger_Appended":
                return True                                    # BYPASS
            if not ledger.verify(prev.attributes["token"],
                                 span.attributes["action_id"]):
                return True                                    # forged / mismatched token
    return False
```

A bypass means the consent gate was circumvented — a tool ran without a real, ledgered
token. There is no benign explanation; it is treated as P0.

## The kill switch

On a detected bypass the evaluator triggers an automated P0 response:

1. **Revoke API keys** — Drive, Resend, Fetch.ai (and any minted scoped tokens).
2. **Freeze the session** — terminate the orchestrator, refuse new `ProposedAction`s.
3. **Alert the user** — *"I've shut myself down — an action tried to run without your
   approval. Nothing else will happen until you re-authorize me."*
4. **Quarantine the trace** for forensic review and preserve the ledger (append-only).

The kill switch favors a false shutdown over a true bypass. A halted assistant is a
recoverable inconvenience; an un-consented side effect is not.
