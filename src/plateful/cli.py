"""Interactive CLI chat for testing the catering agent locally."""

import asyncio
import json

import anthropic

from plateful.agents.execution import ExecutionAgent
from plateful.agents.learning import LearningAgent
from plateful.agents.memory import MemoryAgent
from plateful.agents.menu import MenuAgent
from plateful.agents.planner import PlannerAgent
from plateful.agents.recommendation import RecommendationAgent
from plateful.core.config import settings
from plateful.core.mem0_client import get_mem0_client
from plateful.core.orchestrator import run_planned_workflow
from plateful.core.seed_data import SAMPLE_MENU
from plateful.core.workflow import WorkflowState


def _build_registry() -> dict:  # type: ignore[type-arg]
    claude_client = None
    if settings.anthropic_api_key:
        claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Memory + Learning agents (require Mem0 API key)
    registry: dict = {  # type: ignore[type-arg]
        "menu": MenuAgent(menu_data=SAMPLE_MENU),
        "recommendation": RecommendationAgent(anthropic_client=claude_client),
        "execution": ExecutionAgent(),
    }
    if settings.mem0_api_key:
        mem0_client = get_mem0_client()
        registry["memory"] = MemoryAgent(client=mem0_client)
        registry["learning"] = LearningAgent(client=mem0_client)

    return registry


def _build_planner() -> PlannerAgent:
    claude_client = None
    if settings.anthropic_api_key:
        claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    if claude_client:
        return PlannerAgent(mode="llm", anthropic_client=claude_client)
    return PlannerAgent(mode="keyword")


async def chat_loop() -> None:
    user_id = "emp_demo"
    session_id = "sess_demo"
    registry = _build_registry()
    planner = _build_planner()

    print("=" * 60)
    print("  Plateful AI — Catering Agent")
    if settings.anthropic_api_key:
        print("  Orchestrator: LLM Planner (Claude)")
    else:
        print("  Orchestrator: Keyword fallback (no ANTHROPIC_API_KEY)")
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

        state = await run_planned_workflow(state, registry, planner)

        print(f"\n  Intent: {state.intent}")
        if state.constraints:
            print(f"  Constraints: {json.dumps(state.constraints)}")
        if state.menu_items:
            print(f"  Filtered items: {len(state.menu_items)}")

        # Show recommendation
        if state.recommendation_text:
            print(f"\n{state.recommendation_text}")

        # Show order confirmation
        if state.order:
            order = state.order
            status = order.get("status", "unknown")
            order_id = order.get("order_id", "")
            items = order.get("items", [])
            item_names = ", ".join(i.get("name", "?") for i in items)
            total = order.get("total_usd", 0)
            if status == "submitted":
                print(f"\n  Order placed! #{order_id}: {item_names} (${total:.2f})")
            elif status == "pending_approval":
                print(f"\n  Order #{order_id} is pending approval: {item_names}")
            elif status == "blocked":
                print(f"\n  Order blocked: {order.get('reason', 'policy violation')}")

        if state.intent == "declare_preference" and not state.recommendation_text:
            print("\n  Got it, I'll remember that!")
        print()


def main() -> None:
    asyncio.run(chat_loop())


if __name__ == "__main__":
    main()
