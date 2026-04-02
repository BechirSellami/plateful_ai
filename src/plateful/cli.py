"""Interactive CLI chat for testing the catering agent locally."""

import asyncio
import json

import anthropic

from plateful.agents.intent import IntentAgent
from plateful.agents.learning import LearningAgent
from plateful.agents.memory import MemoryAgent
from plateful.agents.menu import MenuAgent
from plateful.agents.recommendation import RecommendationAgent
from plateful.core.config import settings
from plateful.core.mem0_client import get_mem0_client
from plateful.core.orchestrator import run_adaptive_workflow
from plateful.core.seed_data import SAMPLE_MENU
from plateful.core.workflow import WorkflowState


def _build_registry() -> dict:  # type: ignore[type-arg]
    claude_client = None
    if settings.anthropic_api_key:
        claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    intent_agent = (
        IntentAgent(mode="llm", anthropic_client=claude_client) if claude_client else IntentAgent()
    )

    # Memory + Learning agents (require Mem0 API key)
    registry: dict = {  # type: ignore[type-arg]
        "orchestrator": intent_agent,
        "menu": MenuAgent(menu_data=SAMPLE_MENU),
        "recommendation": RecommendationAgent(anthropic_client=claude_client),
    }
    if settings.mem0_api_key:
        mem0_client = get_mem0_client()
        registry["memory"] = MemoryAgent(client=mem0_client)
        registry["learning"] = LearningAgent(client=mem0_client)

    return registry


async def chat_loop() -> None:
    user_id = "emp_demo"
    session_id = "sess_demo"
    registry = _build_registry()

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

        state = await run_adaptive_workflow(state, registry)

        print(f"\n  Intent: {state.intent}")
        if state.constraints:
            print(f"  Constraints: {json.dumps(state.constraints)}")
        if state.menu_items:
            print(f"  Filtered items: {len(state.menu_items)}")

        # Show recommendation
        if state.recommendation_text:
            print(f"\n{state.recommendation_text}")
        elif state.intent == "declare_preference":
            print("\n  Got it, I'll remember that!")
        print()


def main() -> None:
    asyncio.run(chat_loop())


if __name__ == "__main__":
    main()
