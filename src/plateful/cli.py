"""Interactive CLI chat for testing the catering agent locally."""

import asyncio
import json

import anthropic

from plateful.agents.intent import IntentAgent
from plateful.agents.memory import MemoryAgent
from plateful.agents.menu import MenuAgent
from plateful.agents.recommendation import RecommendationAgent
from plateful.core.config import settings
from plateful.core.mem0_client import get_mem0_client
from plateful.core.orchestrator import run_workflow
from plateful.core.seed_data import SAMPLE_MENU
from plateful.core.workflow import WorkflowState


def _build_flow(registry: dict) -> dict:  # type: ignore[type-arg]
    """Build the workflow flow definition, including memory step if available."""
    steps: list[dict[str, str]] = [
        {"name": "understand", "agent": "orchestrator"},
    ]
    if "memory" in registry:
        steps.append({"name": "enrich", "agent": "memory"})
    steps.extend([
        {"name": "retrieve", "agent": "menu"},
        {"name": "recommend", "agent": "recommendation"},
    ])
    return {"steps": steps}


def _build_registry() -> dict:  # type: ignore[type-arg]
    claude_client = None
    if settings.anthropic_api_key:
        claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    intent_agent = (
        IntentAgent(mode="llm", anthropic_client=claude_client)
        if claude_client
        else IntentAgent()
    )

    # Memory agent (requires Mem0 API key)
    memory_agent = None
    if settings.mem0_api_key:
        memory_agent = MemoryAgent(client=get_mem0_client())

    registry: dict = {  # type: ignore[type-arg]
        "orchestrator": intent_agent,
        "menu": MenuAgent(menu_data=SAMPLE_MENU),
        "recommendation": RecommendationAgent(anthropic_client=claude_client),
    }
    if memory_agent:
        registry["memory"] = memory_agent

    return registry


async def chat_loop() -> None:
    user_id = "emp_demo"
    session_id = "sess_demo"
    registry = _build_registry()
    flow = _build_flow(registry)

    print("=" * 60)
    print("  Plateful AI — Catering Agent")
    if settings.anthropic_api_key:
        print("  Mode: LLM-powered recommendations (Claude)")
    else:
        print("  Mode: Deterministic only (no ANTHROPIC_API_KEY)")
    if "memory" in registry:
        print("  Memory: Mem0 Cloud (user preferences enabled)")
    else:
        print("  Memory: Disabled (no MEM0_API_KEY)")
    print("  Type a message to interact. Ctrl+C to quit.")
    print("=" * 60)
    print()

    # Show menu
    print("Today's menu:")
    for item in SAMPLE_MENU:
        allergens = ", ".join(item.get("allergens", []))
        print(f"  {item['name']:30s} ${item['price_usd']:>6.2f}  [{allergens}]")
    print()

    while True:
        try:
            message = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not message:
            continue

        state = WorkflowState(
            user_id=user_id,
            session_id=session_id,
            messages=[{"role": "user", "content": message}],
        )

        state = await run_workflow(flow, state, registry)

        print(f"\n  Intent: {state.intent}")
        if state.constraints:
            print(f"  Constraints: {json.dumps(state.constraints)}")
        print(f"  Filtered items: {len(state.menu_items)}")

        # Show recommendation
        if state.last_result and isinstance(state.last_result, str):
            print(f"\n{state.last_result}")
        print()


def main() -> None:
    asyncio.run(chat_loop())


if __name__ == "__main__":
    main()
