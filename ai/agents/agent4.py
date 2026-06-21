"""Communication sub-agent — iMessage and phone calls."""
from pydantic_ai import Agent, RunContext

from ai.agents.consent import gate
from ai.agents.deps import OrchestratorDeps
from ai.prompts import load_prompt
from schemas.agent4 import CommunicationRequest, CommunicationResult

_communication_agent: Agent | None = None

_DEFAULT_CONTACTS: list[dict] = [
    {"name": "Tom Nguyen", "phone": "9253197021"},
    {"name": "Khoi Duong", "phone": "9258608099"},
]


def get_communication_agent() -> Agent:
    global _communication_agent
    if _communication_agent is None:
        from config import settings
        from observability.phoenix import get_agent_instrumentation

        _communication_agent = Agent(
            model=settings.ai_model,
            name="communication_agent",
            system_prompt=load_prompt("communication_agent"),
            output_type=CommunicationResult,
            deps_type=OrchestratorDeps,
            capabilities=get_agent_instrumentation(),
        )

        @_communication_agent.tool
        async def search_contact(ctx: RunContext[OrchestratorDeps], name: str) -> list[dict]:
            """Search macOS Contacts by name and return matching entries with phone numbers."""
            from tools.communication import search_contact as _search
            results: list[dict] = list(_search(name))

            # Merge built-in default contacts if not already present.
            q = name.lower().strip()
            existing_names = {r.get("name", "").lower() for r in results}
            for contact in _DEFAULT_CONTACTS:
                cn = contact["name"].lower()
                if (q in cn or cn in q) and cn not in existing_names:
                    results.append(contact)

            if not results:
                return [{"name": name, "phone": "No contacts found."}]
            return results

        @_communication_agent.tool
        async def send_imessage(
            ctx: RunContext[OrchestratorDeps], request: CommunicationRequest
        ) -> str:
            """Send an iMessage to a contact."""
            from tools.communication import send_imessage as _send
            msg = request.imessage

            async def _execute() -> str:
                success = _send(recipient=msg.recipient, body=msg.body)
                if success:
                    return f"iMessage sent to {msg.recipient}."
                return f"Failed to send iMessage to {msg.recipient}."

            return await gate(
                ctx,
                action_type="comms.imessage",
                agent="communication_agent",
                summary=f"Send iMessage to {msg.recipient}: '{msg.body[:60]}{'…' if len(msg.body) > 60 else ''}'",
                payload={"recipient": msg.recipient, "body": msg.body},
                execute=_execute,
            )

        @_communication_agent.tool
        async def make_call(
            ctx: RunContext[OrchestratorDeps], request: CommunicationRequest
        ) -> str:
            """Initiate a phone call to a contact."""
            from tools.communication import make_call as _call
            call = request.call

            async def _execute() -> str:
                success = _call(recipient=call.recipient)
                if success:
                    return f"Calling {call.recipient}..."
                return f"Failed to initiate call to {call.recipient}."

            return await gate(
                ctx,
                action_type="comms.call",
                agent="communication_agent",
                summary=f"Call {call.recipient}",
                payload={"recipient": call.recipient},
                execute=_execute,
            )

    return _communication_agent
