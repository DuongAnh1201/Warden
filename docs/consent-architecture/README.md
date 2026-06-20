# MoneyPenny — Consent Architecture

> The security spine of MoneyPenny: a **default-deny** boundary around the LLM's output.
> The orchestrator is *structurally incapable* of producing a real-world side effect
> without a verifiable token of human approval.

This folder is the watertight version of the consent design. It is the source of truth
for the four invariants below; the product README describes the experience, these docs
describe the guarantee.

## The four invariants

1. **No token, no effect.** Every external API wrapper (Resend, Google Drive, Calendar,
   Fetch.ai) refuses to run without a valid `Consent_Token`. The token is checked in the
   wrapper itself, not in the orchestrator — so a hallucinated tool call fails closed.
2. **No effect without a ledger entry.** Every executed action is preceded by a
   `[Ledger_Appended]` span in the same trace. This holds for *silent* actions too —
   silent never means untracked.
3. **Fail closed, always.** Timeouts, low-confidence speech, network desync, and partial
   failures all resolve to "nothing happened" or "rolled back," never "did it anyway."
4. **The guarantee is checked, not claimed.** A continuous Arize Phoenix evaluator audits
   traces and trips a kill switch if a `[Tool_Executed]` span ever lacks a preceding,
   valid `[Ledger_Appended]`.

## Documents

| Doc | Phase | What it defines |
|---|---|---|
| [`01-consent-gate.md`](./01-consent-gate.md) | 1 | Zero-trust middleware, `ProposedAction`, Redis state, the `Consent_Token`, the execution lock |
| [`02-fallback-matrix.md`](./02-fallback-matrix.md) | 2 | How MoneyPenny fails closed on timeout, ambiguity, desync, hallucination, and post-consent API failure |
| [`03-observability-and-ledger.md`](./03-observability-and-ledger.md) | 3 | Phoenix tracing, the consent-bypass evaluator, the kill switch |
| [`04-trust-tiers.md`](./04-trust-tiers.md) | 4 | **Criteria for which low-risk actions earn a silent, revertible notification instead of a hard verbal stop** |

## How a real-world action flows (the healthy trace)

```
[Intent_Generated] → [Tier_Classified] → [Gate_Paused] → [Voice_Approval]
        → [Ledger_Appended] → [Tool_Executed]
```

For a Tier 0 (silent) action the human pause is replaced by an auto-issued token plus a
pre-registered rollback — but the `[Ledger_Appended] → [Tool_Executed]` ordering is
**identical**, which is exactly what keeps the kill-switch evaluator valid for every tier.
See [`04-trust-tiers.md`](./04-trust-tiers.md).
