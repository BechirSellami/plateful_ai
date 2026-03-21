"""Interactive CLI chat for testing the catering agent locally."""

import asyncio
import json

from plateful.agents.intent import IntentAgent
from plateful.agents.menu import MenuAgent
from plateful.core.orchestrator import run_workflow
from plateful.core.seed_data import SAMPLE_MENU
from plateful.core.workflow import WorkflowState

FLOW = {
    "steps": [
        {"name": "understand", "agent": "orchestrator"},
        {"name": "retrieve", "agent": "menu"},
    ]
}

REGISTRY = {
    "orchestrator": IntentAgent(),
    "menu": MenuAgent(menu_data=SAMPLE_MENU),
}


async def chat_loop() -> None:
    user_id = "emp_demo"
    session_id = "sess_demo"

    print("=" * 60)
    print("  Plateful AI — Catering Agent (local mode)")
    print("  Type a message to interact. Ctrl+C to quit.")
    print("=" * 60)
    print()

    # Show available menu
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

        state = await run_workflow(FLOW, state, REGISTRY)

        print(f"\n  Intent: {state.intent}")
        if state.constraints:
            print(f"  Constraints: {json.dumps(state.constraints)}")
        print(f"  Matching items ({len(state.menu_items)}):")
        for item in state.menu_items:
            allergens = ", ".join(item.get("allergens", []))
            print(f"    - {item['name']:30s} ${item['price_usd']:>6.2f}  [{allergens}]")
        print()


def main() -> None:
    asyncio.run(chat_loop())


if __name__ == "__main__":
    main()
