"""Interactive CLI chat for testing the catering agent locally."""

import asyncio
import json

import anthropic

from plateful.agents.intent import IntentAgent
from plateful.agents.menu import MenuAgent
from plateful.agents.recommendation import RecommendationAgent
from plateful.core.config import settings
from plateful.core.orchestrator import run_workflow
from plateful.core.seed_data import SAMPLE_MENU
from plateful.core.workflow import WorkflowState

FLOW = {
    "steps": [
        {"name": "understand", "agent": "orchestrator"},
        {"name": "retrieve", "agent": "menu"},
        {"name": "recommend", "agent": "recommendation"},
    ]
}


def _build_registry() -> dict:  # type: ignore[type-arg]
    claude_client = None
    if settings.anthropic_api_key:
        claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    return {
        "orchestrator": IntentAgent(),
        "menu": MenuAgent(menu_data=SAMPLE_MENU),
        "recommendation": RecommendationAgent(anthropic_client=claude_client),
    }


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

        state = await run_workflow(FLOW, state, registry)

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
