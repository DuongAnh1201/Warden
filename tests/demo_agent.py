"""Minimal echo agent for agent-to-agent demo.

Local usage (two terminals):
    terminal 1:  uv run python -m ai.transport.fetch_wrapper
    terminal 2:  uv run python tests/demo_agent.py

Then in the chat UI:
    "Ask the agent at <address> what the weather is"

The echo agent replies with:  ECHO from DemoAgent: <your message>
You will see the full round-trip in both terminals' logs.

Cloud usage (agent lives on Agentverse):
    Set AGENTVERSE_API_KEY in environment and the agent runs in mailbox mode,
    reachable from anywhere including Railway-deployed MoneyPenny.
"""
import os

from uagents import Agent, Context, Model


class SSSRequest(Model):
    text: str
    user_id: str = "agent_guest"
    correlation_id: str = ""


class SSSResponse(Model):
    text: str
    intent: str = "echo"
    success: bool = True
    correlation_id: str = ""


_api_key = os.getenv("AGENTVERSE_API_KEY", "")

demo = Agent(
    name="demo_echo_agent",
    seed="demo-echo-agent-seed-for-local-testing-only",
    port=8002,
    mailbox=bool(_api_key),
)


@demo.on_event("startup")
async def on_start(ctx: Context) -> None:
    mode = "mailbox (cloud-reachable)" if _api_key else "local only (port 8002)"
    print()
    print("=" * 60)
    print("  Demo Echo Agent")
    print(f"  Address : {demo.address}")
    print(f"  Mode    : {mode}")
    print()
    print("  Paste this into the chat UI:")
    print(f'  "Send a message to agent at {demo.address} saying hello"')
    print("=" * 60)
    print()


@demo.on_message(model=SSSRequest, replies={SSSResponse})
async def handle(ctx: Context, sender: str, msg: SSSRequest) -> None:
    print(f"[demo_agent] ← from {sender[:24]}: {msg.text}")
    reply = f"ECHO from DemoAgent: {msg.text}"
    print(f"[demo_agent] → replying: {reply}")
    await ctx.send(sender, SSSResponse(
        text=reply,
        intent="echo",
        success=True,
        correlation_id=msg.correlation_id,
    ))


if __name__ == "__main__":
    demo.run()
