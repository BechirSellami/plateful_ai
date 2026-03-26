"""Tools for the Learning Agent to log events and consolidate into memories."""

from typing import Any

import structlog

logger = structlog.get_logger()


def summarize_session_events(events: list[dict[str, Any]]) -> str:
    """Convert structured events into a natural language summary for Mem0.

    This is the bridge between application-level events and semantic memory.
    The summary is passed to Mem0 which extracts and stores memories.
    """
    if not events:
        return ""

    signals: list[str] = []

    for event in events:
        event_type = event.get("event_type", "")
        payload = event.get("payload", {})

        if event_type == "order_placed":
            item_name = payload.get("item_name", "an item")
            price = payload.get("price_usd", "")
            signals.append(f"User ordered {item_name}" + (f" (${price})" if price else ""))

        elif event_type == "item_added":
            item_name = payload.get("item_name", "an item")
            signals.append(f"User added {item_name} to their order")

        elif event_type == "item_removed":
            item_name = payload.get("item_name", "an item")
            signals.append(f"User removed {item_name} from their order")

        elif event_type == "item_swapped":
            old_item = payload.get("old_item", "an item")
            new_item = payload.get("new_item", "another item")
            signals.append(f"User swapped {old_item} for {new_item}")

        elif event_type == "suggestion_accepted":
            item_name = payload.get("item_name", "a suggestion")
            signals.append(f"User accepted suggestion: {item_name}")

        elif event_type == "suggestion_rejected":
            item_name = payload.get("item_name", "a suggestion")
            signals.append(f"User rejected suggestion: {item_name}")

        elif event_type == "rating_given":
            item_name = payload.get("item_name", "an item")
            rating = payload.get("rating", "")
            signals.append(f"User rated {item_name}: {rating}/5")

        elif event_type == "allergy_declared":
            allergen = payload.get("ingredient", "something")
            signals.append(f"User declared allergy to {allergen}")

        elif event_type == "mealplan_edited":
            day = payload.get("day", "a day")
            signals.append(f"User edited meal plan for {day}")

    return ". ".join(signals)


def build_mem0_messages(summary: str) -> list[dict[str, str]]:
    """Wrap the session summary into Mem0 message format."""
    if not summary:
        return []

    return [
        {
            "role": "user",
            "content": (
                f"Here is a summary of the user's recent catering session: {summary}. "
                "Please extract any food preferences, dietary restrictions, "
                "budget habits, or taste patterns from this behavior."
            ),
        }
    ]
