"""Text-mode harness for the Moneypenny orchestrator.

Usage:

    uv run python run_text.py --check
        Import everything and build all agents. No network calls.
        Verifies the full wiring is correct. Exits non-zero on failure.

    uv run python run_text.py "Email Priya that the deck is ready"
        Run the orchestrator against a typed request. The consent gate
        will prompt you on the console before any action fires.

    uv run python run_text.py --yes "Email Priya that the deck is ready"
        Same, but auto-approves all gated actions (still writes to the ledger).
        Useful for CI / non-interactive smoke runs.

    uv run python run_text.py --user alice "What did I tell you about the project?"
        Run as a specific user. History and knowledge are loaded from Redis
        under that user's namespace (requires REDIS_URL in .env).
"""

from __future__ import annotations

import asyncio
import sys


def build_check() -> None:
    """Import tools and construct every agent to validate wiring."""
    from ai.prompts import load_prompt
    from ai.agents.orchestrator import get_orchestrator
    from ai.agents.agent1 import get_email_agent
    from ai.agents.agent2 import get_calendar_agent
    from ai.agents.agent3 import get_search_agent
    from ai.agents.agent4 import get_communication_agent
    from ai.agents.agent5 import get_knowledge_base_agent
    from ai.agents.agent6 import get_gmail_agent
    from ai.agents.agent7 import get_drive_agent
    import tools.sending_email  # noqa: F401
    import tools.calendar  # noqa: F401
    import tools.communication  # noqa: F401
    import tools.knowledge_base  # noqa: F401
    import tools.gmail  # noqa: F401
    import tools.google_drive  # noqa: F401
    import tools.ledger  # noqa: F401

    for name in (
        "orchestrator",
        "email_agent",
        "calendar_agent",
        "search_agent",
        "communication_agent",
        "knowledge_base_agent",
        "gmail_agent",
        "drive_agent",
        "tombio",
    ):
        load_prompt(name)

    agents = {
        "orchestrator": get_orchestrator(),
        "email": get_email_agent(),
        "calendar": get_calendar_agent(),
        "search": get_search_agent(),
        "communication": get_communication_agent(),
        "knowledge_base": get_knowledge_base_agent(),
        "gmail": get_gmail_agent(),
        "drive": get_drive_agent(),
    }
    print("OK — prompts loaded, tools imported, agents built:")
    for label, agent in agents.items():
        print(f"  - {label}: {agent.name}")


# ── Console approver ───────────────────────────────────────────────────────────


async def _console_approver(req) -> object:
    """Present an ActionRequest to the user on stdout and read their decision."""
    from schemas.consent import ActionDecision

    print()
    print("─" * 60)
    print(f"  ACTION REQUIRED  ({req.action_type})")
    print(f"  {req.summary}")
    print("─" * 60)
    print("  approve / cancel / revise <note>")
    print()

    while True:
        try:
            raw = await asyncio.to_thread(input, "  Your decision: ")
        except EOFError:
            raw = "cancel"

        raw = raw.strip()
        lower = raw.lower()

        if lower in ("approve", "yes", "y", "ok", "send it"):
            print()
            return ActionDecision(action_id=req.action_id, decision="approve")

        if lower in ("cancel", "no", "n", "cancel it"):
            print()
            return ActionDecision(action_id=req.action_id, decision="cancel")

        if lower.startswith("revise"):
            note = raw[6:].strip(" :")
            print()
            return ActionDecision(
                action_id=req.action_id, decision="revise", revision_note=note
            )

        print("  Please type: approve / cancel / revise <note>")


async def _print_ledger_tail(ledger, limit: int = 5) -> None:
    """Print the most recent ledger entries after a run."""
    entries = await ledger.history(limit=limit)
    if not entries:
        return
    print()
    print("── Consent ledger (last %d) ──────────────────────────" % len(entries))
    for e in entries:
        dec = e.decision.decision if e.decision else "pending"
        print(f"  [{e.outcome:10s}] [{dec:8s}] {e.request.summary[:55]}")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

async def run_once(
    prompt: str,
    auto_approve: bool = False,
    user_id: str = "default",
) -> None:
    from config import settings
    from ai.agents.orchestrator import get_orchestrator
    from ai.agents.deps import OrchestratorDeps
    from tools.ledger import get_ledger

    # ── Phase 4: graph knowledge + execution log (when REDIS_URL is set) ────────
    knowledge = None
    execution_log = None
    if settings.redis_url:
        try:
            from memory.execution_log import get_execution_log
            execution_log = get_execution_log()
        except Exception as exc:
            print(f"[execution_log] skipped — {exc}", flush=True)
        if settings.openai_api_key:
            try:
                from memory.graph import get_graph_knowledge
                knowledge = get_graph_knowledge()
            except Exception as exc:
                print(f"[graph_knowledge] skipped — {exc}", flush=True)

    ledger = get_ledger()

    # Load Workspace credentials if the user has connected (else None => demo mode).
    workspace_creds = None
    try:
        from tools.google_auth import get_workspace_credentials, granted_scopes

        workspace_creds = get_workspace_credentials()
        if workspace_creds is not None:
            print(f"[workspace] connected — scopes: {', '.join(granted_scopes()) or 'none'}")
    except Exception as e:  # noqa: BLE001 — never block a run on workspace wiring
        print(f"[workspace] not connected ({e}); calendar/gmail run in demo mode")

    deps = OrchestratorDeps(
        user_id=user_id,
        knowledge=knowledge,
        execution_log=execution_log,
        ledger=ledger,
        auto_approve=auto_approve,
        request_approval=None if auto_approve else _console_approver,
        workspace_creds=workspace_creds,
    )

    result = await get_orchestrator().run(prompt, deps=deps)
    print(result.output)
    await _print_ledger_tail(ledger)


async def connect_workspace() -> None:
    """Interactive Workspace connect: scope menu -> OAuth -> store token -> ledger."""
    from tools.google_auth import (
        connect,
        granted_scopes,
        log_workspace_event,
        prompt_scope_selection,
        resolve_scopes,
        summarize_selection,
    )
    from tools.ledger import get_ledger

    selection = prompt_scope_selection()
    if not resolve_scopes(selection):
        print("Nothing selected — every surface is off. Aborting.")
        return
    try:
        connect(selection)
    except RuntimeError as e:
        print(f"Could not connect: {e}")
        return
    summary = summarize_selection(selection)
    await log_workspace_event(get_ledger(), "workspace.connect", f"Connected Workspace — {summary}", selection)
    print(f"\nConnected. Granted scopes:\n  " + "\n  ".join(granted_scopes()))


async def disconnect_workspace() -> None:
    """Revoke the Workspace grant and record it in the ledger."""
    from tools.google_auth import revoke, log_workspace_event
    from tools.ledger import get_ledger

    removed = revoke()
    await log_workspace_event(get_ledger(), "workspace.revoke", "Disconnected Workspace", {})
    print("Workspace disconnected." if removed else "No active Workspace connection.")


def main() -> None:
    args = sys.argv[1:]

    if not args or args[0] == "--check":
        build_check()
        return

    if args[0] == "--connect":
        asyncio.run(connect_workspace())
        return

    if args[0] == "--disconnect":
        asyncio.run(disconnect_workspace())
        return

    auto_approve = False
    user_id = "default"

    while args:
        if args[0] == "--yes":
            auto_approve = True
            args = args[1:]
        elif args[0] == "--user" and len(args) > 1:
            user_id = args[1]
            args = args[2:]
        else:
            break

    if not args:
        print(
            "Usage: run_text.py [--check | --connect | --disconnect | "
            "[--yes] [--user <id>] <prompt>]"
        )
        sys.exit(1)

    asyncio.run(run_once(" ".join(args), auto_approve=auto_approve, user_id=user_id))


if __name__ == "__main__":
    main()
