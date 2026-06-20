# Phase 4 — Trust Tiers

> **The question:** which low-risk actions can earn a **silent, easily revertible
> notification** instead of a hard verbal stop — and what are the exact criteria?

The goal is to remove friction from genuinely harmless actions **without weakening the
default-deny guarantee.** The boundary is drawn by *reversibility and blast radius*, never
by convenience. An action does not become silent because it's annoying to confirm; it
becomes silent because, if MoneyPenny got it wrong, undoing it costs the user nothing.

## The three tiers

| Tier | Behavior | When the token is minted | Default for |
|---|---|---|---|
| **2 — Hard Stop** | Blocking. MoneyPenny pauses and waits for a spoken "yes." | On verbal approval | **Everything by default** + anything irreversible or externally observable |
| **1 — Soft Confirm** | Non-blocking voice/visual notice with a short undo window; executes unless countermanded. | On notice delivery, consumed at window close | Low-risk but mildly external or only partly reversible |
| **0 — Silent** | Auto-executes. Posts a passive notification. A pre-registered rollback stays armed for a revert window. | Auto-issued *with* a registered compensating action | Fully reversible, self-contained, zero-observer actions |

**Tier 2 is the floor for unknowns.** An action is only allowed *down* to Tier 1 or Tier 0
if it provably passes the gates below. Default-deny means: unclassified → Tier 2.

## The Tier 0 gate — all six must be TRUE

An action qualifies for **silent + revertible** only if **every** predicate holds. This is
a hard AND; any single failure escalates the action to (at least) Tier 1.

| Gate | Predicate | Rationale |
|---|---|---|
| **G1 — Self-revertible** | A deterministic compensating action exists that fully restores the prior state, executable by MoneyPenny **alone**, with no third-party or peer-agent cooperation. | "Easily revertible" must be a *guarantee we own*, not a hope that someone cooperates. |
| **G2 — Zero external observers** | No third party can observe the effect during the revert window. | If someone can already see it, an "undo" doesn't undo the disclosure. |
| **G3 — No value transfer / commitment** | No money spent, no booking, no promise, no consumed resource that can't be reclaimed. | Commitments are, by nature, not silently revertible. |
| **G4 — No sensitive-data egress** | The action does not move private data outside the user's trust boundary. | Confidentiality breaches are irreversible the moment they leave. |
| **G5 — Bounded, owned scope** | A single, well-typed target the user already owns. Not bulk/fan-out, not crossing the agent network. | Caps blast radius if the classifier or the LLM is wrong. |
| **G6 — High intent confidence** | Deepgram confidence `≥ 0.85` **and** unambiguous intent (no conflicting clauses). | Reuses the Phase 2 threshold; low confidence can never be silent. |

Plus a window requirement:

- **W — Revert window:** the effect stays fully revertible for **≥ 60s**, during which the
  passive notification is live and a single word ("undo" / "no") rolls it back. If the
  notification can't be delivered, the action **aborts** rather than running silently
  (see Phase 2).

## Auto-disqualifiers — any one forces Tier 2

These short-circuit the gate. If any is true, the action is a hard stop, full stop:

- Irreversible, or externally observable the instant it fires (send / post / call / pay).
- Crosses the agent network (Fetch.ai) or touches another human's calendar/inbox →
  always Tier 2 + two-phase commit.
- Deletes or overwrites user data without a retained backup.
- Confidence `< 0.85` or conflicting speech.
- A novel/unenumerated action type (default-deny the unknown).

## Reversibility classes (how G1 is decided)

| Class | Meaning | Max tier eligible |
|---|---|---|
| **R0** | Fully reversible by MoneyPenny alone, no trace left for others | Tier 0 |
| **R1** | Reversible, but needs external cooperation or leaves an observable trace | Tier 1 |
| **R2** | Irreversible or externally committed | Tier 2 |

`R0` is a precondition for Tier 0. `R1` caps an action at Tier 1. `R2` is always Tier 2.

## Concrete classification (the static allowlist)

This is the code-defined map — assigned by the gate, never by the LLM. Context can only
raise the tier (stricter), never lower it below this floor.

| Action | Reversibility | Tier | Why |
|---|---|---|---|
| Draft an email (no send) | R0 | **0** | Lives in the user's own draft space; delete to revert; no observer. |
| Save a note / file to the user's own Drive scratch space | R0 | **0** | Owned target, deletable, not shared. |
| Set a personal reminder / alarm | R0 | **0** | Self-only, cancelable. |
| Apply a label / file / tag to the user's own item | R0 | **0** | Reversible relabel, no external effect. |
| Add a **private** event to the user's own calendar (no attendees) | R0 | **0** | Deletable, no invites sent, no observer. |
| Reschedule the user's own no-attendee event | R0 | **0** | Move back to revert; nobody notified. |
| Search the web / read a file | R0 (read-only) | **0** | No side effect at all. |
| Move a file the user owns into a folder | R1 | **1** | Reversible, but may surface in others' shared views. |
| Cancel a previously-scheduled (already-sent) item | R1 | **1** | Partly observable; soft-confirm. |
| **Send an email** (Resend) | R2 | **2** | Instantly observed by a third party; not revertible. |
| **Send a message / place a call** | R2 | **2** | External + irreversible. |
| **Share a Drive file externally** | R2 | **2** | Data egress; G4 fails. |
| **Create a calendar event with attendees / send invites** | R2 | **2** | Touches another human; G2/G5 fail. |
| **Any spend / booking / payment** | R2 | **2** | Commitment; G3 fails. |
| **Any agent-to-agent action** (Fetch.ai) | R2 | **2** | Two-sided; requires two-phase commit + both humans. |

## How Tier 0 stays watertight (it does **not** weaken default-deny)

Silent does **not** mean unguarded. A Tier 0 action still produces a token, a ledger
entry, and a full Phoenix trace — it just replaces the human pause with two automatic,
auditable steps performed *before* execution:

```
[Intent_Generated] → [Tier_Classified:0] → [Auto_Consent_Issued]
        → [Rollback_Registered] → [Ledger_Appended] → [Tool_Executed]
        → [Revert_Window_Open]
```

```python
def run_silent_action(action: ProposedAction):
    assert tier_classifier.classify(action) == ConsentTier.SILENT     # static, not LLM
    rollback = build_compensating_action(action)                      # G1 — must exist
    if rollback is None:
        return escalate(action, ConsentTier.HARD_STOP)                # no undo → not silent
    token  = mint_auto_consent_token(action.action_id)                # still a real token
    ledger.append(action, token, decision="auto_silent",
                  rollback=rollback)                                  # still ledgered
    notify_user_passively(action)                                     # W — must deliver
    execute(action, consent_token=token)                              # execution lock satisfied
    arm_revert_window(action, rollback, seconds=60)                   # one word undoes it
```

Key properties:

- **The execution lock is unchanged.** The wrapper still demands a valid token; Tier 0 just
  supplies an auto-issued one. A hallucinated direct call still has no token and still fails.
- **The kill-switch evaluator is unchanged.** `[Ledger_Appended] → [Tool_Executed]` holds
  for Tier 0 exactly as for Tier 2 (see Phase 3), so silent actions are audited identically.
- **Rollback is registered *before* execution**, not improvised after. If a compensating
  action can't be built, the action can't be silent — it escalates.

## Governance rails

- **Static assignment.** Tiers come from the code-defined allowlist, not the model.
- **Stricter-only overrides.** The user (or context) can *promote* any action to a higher
  tier — e.g. mark a VIP contact, or require confirmation for all calendar changes — but
  can never demote a statically Tier 2 action below Tier 1. Adjustments fail-closed.
- **Context ceilings.** Heuristics raise the tier automatically: large recipient list,
  flagged contact, unusually large/old target, off-hours, or anomalous frequency.
- **Silent-action budget.** A rolling rate limit (e.g. ≤ 10 silent actions / 5 min) caps
  the blast radius of a classifier bug; exceeding it forces a checkpoint with the user.
- **Revert window must be honored.** The token is consumed only after the passive
  notification is confirmed delivered; if it can't be delivered, abort.
- **Every silent action is in the ledger and reviewable** — the user can list, audit, and
  retroactively revert anything MoneyPenny did silently.

## One-line summary

> An action goes **silent** only when undoing it is free, owned, unobserved, and
> guaranteed in advance — and even then it is still tokenized, ledgered, traced, rate-
> limited, and one word away from being reversed. Everything else stops and waits for your
> word.
