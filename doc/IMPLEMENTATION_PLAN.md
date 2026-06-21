# Moneypenny — Implementation Plan

> A plan to move the codebase from its current skeleton to the product described in the [README](../README.md): a voice-driven, consent-gated personal assistant whose agents can talk to other agents.

This document is the bridge between **what the README promises** and **what the code currently does**. It records the gap, then lays out a phased path to close it.

---

## 1. The vision (from the README)

Moneypenny is a voice-first assistant that _acts_ on your behalf — email, calendar, search, messaging, Drive — but **every consequential action pauses for your spoken approval**. Its differentiator is **agent-to-agent coordination**: your Moneypenny finds and negotiates with another person's Moneypenny (or a hired specialist agent) over an open network, and humans only say "yes."

Pillars:

1. **Voice I/O** — real-time speech in/out (Deepgram / OpenAI Realtime).
2. **Orchestrator + specialist agents** — Pydantic AI routes intent to email/calendar/search/comms/knowledge/drive agents.
3. **Consent gate** — approve / cancel / revise, by voice, on every real action.
4. **Memory & knowledge** — cross-session memory + semantic recall (Redis).
5. **Consent ledger + safety evals** — every decision logged (Redis Streams) and self-checked (Arize Phoenix).
6. **Open agent network** — discover, talk to, and pay other agents (Fetch.ai / uAgents).

---

## 2. What already exists (current state)

The Python package is a **Pydantic-AI multi-agent skeleton**, further along than `main.py` suggests:

| Area                                              | Status            | Location                                                  |
| ------------------------------------------------- | ----------------- | --------------------------------------------------------- |
| Orchestrator agent + delegation tools             | ✅ implemented    | [ai/agents/orchestrator.py](../ai/agents/orchestrator.py) |
| Email sub-agent (with approval hook)              | ✅ implemented    | [ai/agents/agent1.py](../ai/agents/agent1.py)             |
| Calendar sub-agent (CRUD + free/busy)             | ✅ implemented    | [ai/agents/agent2.py](../ai/agents/agent2.py)             |
| Search sub-agent (Serper)                         | ✅ implemented    | [ai/agents/agent3.py](../ai/agents/agent3.py)             |
| Communication sub-agent (iMessage/call)           | ✅ implemented    | [ai/agents/agent4.py](../ai/agents/agent4.py)             |
| Knowledge-base sub-agent                          | ⚠️ buggy (see §3) | [ai/agents/agent5.py](../ai/agents/agent5.py)             |
| Shared deps (incl. `request_email_approval` hook) | ✅                | [ai/agents/deps.py](../ai/agents/deps.py)                 |
| Pydantic schemas for every agent                  | ✅                | [schemas/](../schemas/)                                   |
| Prompt markdown files                             | ✅ present        | [ai/prompts/](../ai/prompts/)                             |
| Settings/config loader                            | ✅                | [config.py](../config.py)                                 |

**The consent-gate pattern already exists in spirit:** `OrchestratorDeps.request_email_approval` is an async callback that, when set, makes the email agent request approval before sending. This is the seed of the whole "consent gate" feature — it just needs to be (a) generalized to every agent and (b) wired to a real UI + ledger.

---

## 3. The gap — what's missing or broken

These are blockers; nothing runs end-to-end today.

### Blocking bugs

- **`tools/` package is empty.** Every agent imports concrete tools that don't exist yet:
  `tools.sending_email`, `tools.calendar`, `tools.communication`, `tools.knowledge_base`, `tools.email_approval`. Importing any agent's tools will fail.
- **`load_prompt` is undefined.** All agents do `from ai.prompts import load_prompt`, but [ai/prompts/**init**.py](../ai/prompts/__init__.py) is empty. The `.md` prompts exist but nothing loads them.
- **`agent5.py` bugs:** uses `settings.model` (config only defines `ai_model`); `read_file`/`update_file`/`add_context` are missing the `@_knowledge_base_agent.tool` decorator; `add_context` reads `request.file_name_1/2` which aren't on `KnowledgeBaseRequest`; the function has no `return _knowledge_base_agent`.
- **`pyproject.toml` declares `dependencies = []`** but the code needs `pydantic-ai`, `pydantic-settings`, `python-dotenv`, `httpx`, `resend`, etc.

### Missing whole subsystems (promised in README, no code yet)

- **No `server.py`** — the README's run command (`uv run python server.py`) has no target.
- **No voice layer** — no Deepgram / OpenAI Realtime integration despite `realtime_model`/`realtime_voice` in config.
- **No frontend** — [frontend/](../frontend/) contains only `__init__.py`; README expects a Node/Vite app.
- **No Redis** — no memory, no semantic knowledge, no consent ledger.
- **No consent ledger** — the approval hook returns a string but nothing is persisted/auditable.
- **No Arize Phoenix** — no tracing / safety evals.
- **No Fetch.ai / agent network** — the headline feature is entirely unbuilt.
- **No Google Drive agent** — listed in README features, not present.
- **Name mismatch** — repo/package is `warden`; product is `Moneypenny`. Pick one and align.

---

## 4. Guiding principles for the build

- **Make it run before making it grand.** Get the existing text-based agent loop working end-to-end first; voice and the network come after.
- **Consent is structural, not bolted on.** Every state-changing tool flows through one gate + one ledger write. Generalize the existing `request_email_approval` pattern into a single `request_approval(action)` mechanism shared by all agents.
- **Demo-mode every real surface.** Messages/Contacts use macOS APIs; Calendar uses the Google Calendar API; email uses Resend. Each provides a simulated backend so the flow runs in CI / on the hosted demo (README already promises this).
- **Slice by user-visible capability,** not by layer — each phase should end in something demoable.

---

## 5. Phased plan

### Phase 0 — Make the skeleton run (foundation)

_Goal: import the orchestrator and run one text request end-to-end._

- Fill `pyproject.toml` dependencies; `uv sync`.
- Implement `ai/prompts/__init__.py::load_prompt(name)` to read `ai/prompts/<name>.md`.
- Implement the `tools/` package with **real macOS tools + a demo/simulation fallback**:
  - `tools/sending_email.py` (Resend), `tools/calendar.py` (Google Calendar API), `tools/communication.py` (Messages/Contacts), `tools/knowledge_base.py` (file-backed), `tools/email_approval.py` (`EmailDraft` + draft model).
- Fix the `agent5.py` bugs listed in §3.
- Add a tiny `run_text.py` harness that feeds a typed string to `get_orchestrator().run(...)`.
- **Done when:** "Email Priya the deck is ready" routes to the email agent and (in demo mode) produces a draft.

### Phase 1 — The consent gate, generalized + ledger

_Goal: every consequential action pauses and is recorded._

- Generalize `request_email_approval` → a single `request_approval(ActionRequest)` callback on `OrchestratorDeps`, used by email, calendar, comms, and drive tools.
- Define an `ActionRequest`/`ActionDecision` schema (action type, human-readable summary, payload, approve/cancel/revise).
- Add the **consent ledger**: append every request + decision to Redis Streams (with a file/in-memory fallback for local dev).
- **Done when:** any send/book/message/spend tool blocks on approval and writes an auditable ledger entry.

### Phase 2 — Backend server + frontend shell

_Goal: a browser app can talk to the assistant over a socket, approve actions, see the ledger._

- Build `server.py` (FastAPI + WebSocket): session handler that owns `OrchestratorDeps`, wires `request_approval` to push approval cards to the client and await the response.
- Scaffold the Vite/React frontend in `frontend/`: power button, transcript, review/approval cards (the README's "review card"), consent-log view.
- Add "Try as Guest" demo persona (per README).
- **Done when:** browser → server → orchestrator → approval card → approve → action fires (demo mode) → ledger updates.

### Phase 3 — Voice layer

_Goal: talk to it._

- Integrate real-time STT/TTS (Deepgram or OpenAI Realtime per `config.py`).
- Stream transcripts into the orchestrator; speak responses and approval prompts; accept spoken "send it / cancel / change the time."
- **Done when:** the full email/calendar flow works hands-free.

### Phase 4 — Memory & knowledge (Redis)

_Goal: it remembers you across sessions._

- Cross-session memory + semantic recall (Redis vector) for preferences, contacts, and "what did I tell you about X."
- Replace the file-backed knowledge agent with the Redis-backed store; load user context into `OrchestratorDeps.history_context`.
- **Done when:** "What did I tell you about the Henderson project last week?" returns a real recalled answer.

### Phase 5 — Trust & observability (Arize Phoenix)

_Goal: prove no action bypassed consent._

- Trace every agent run + tool call.
- Add a self-check eval that reconciles fired actions against the consent ledger and flags any unapproved action.
- **Done when:** there's a report showing every consequential action maps to an approval.

### Phase 6 — The open agent network (Fetch.ai) — _the headline feature_

_Goal: your agent talks to other agents._

- Wrap Moneypenny as a uAgent on Agentverse; register/discover via ASI:One; communicate over the Chat Protocol.
- **Peer-to-peer scheduling:** implement the sequence in the README's mermaid diagram — find peer's agent, exchange free/busy, converge on a slot, route to _both_ consent gates, book on mutual yes.
- **Open-network hiring:** discover a specialist agent, negotiate, and pay via the Payment Protocol — through the consent gate.
- **Done when:** two Moneypenny instances schedule a meeting with no human-to-human messages, each owner approving once.

### Phase 7 — Polish & optional hardware

- Proactive reminders (Moneypenny reaches out first).
- Optional **Moneypenny Orb** hardware companion (LED consent states).

---

## 6. Suggested first PR (concrete next step)

A single "make it boot" PR covering **Phase 0**:

1. `pyproject.toml` dependencies + `uv sync`.
2. `ai/prompts/__init__.py::load_prompt`.
3. `tools/` implementations with demo fallback.
4. `agent5.py` bug fixes.
5. `run_text.py` smoke test.

This unblocks everything else and makes the existing (already substantial) agent code actually executable.

---

## 7. Open decisions

- **Product name:** keep `warden` (package) or rename to `moneypenny` to match the README?
- **Voice provider:** Deepgram (README architecture) vs OpenAI Realtime (already in `config.py`) — pick one.
- **LLM provider:** `config.py` supports OpenAI/Gemini via Pydantic AI; per project guidance, default to the latest Claude models if open to changing.
- **Demo vs native:** how much of calendar/Messages must work natively for the hackathon demo vs simulated.
