"""Minimal echo agent for local agent-to-agent demo.

Run this in a separate terminal:
    uv run python tests/demo_agent.py

It will print its Fetch.ai address. Paste that address into the chat:
    "Ask the agent at agent1q... what the weather is like"

The echo agent replies with:  ECHO from DemoAgent: <your message>
You will see the full round-trip in both terminals' logs.
"""
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


demo = Agent(
    name="demo_echo_agent",
    seed="demo-echo-agent-seed-for-local-testing-only",
    port=8002,
)


@demo.on_event("startup")
async def on_start(ctx: Context) -> None:
    print()
    print("=" * 60)
    print("  Demo Echo Agent")
    print(f"  Address : {demo.address}")
    print()
    print("  Paste this into the chat UI:")
    print(f'  "Ask the agent at {demo.address} what the weather is"')
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
