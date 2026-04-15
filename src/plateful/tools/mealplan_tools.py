"""Tools for generating and editing weekly meal plans.

The meal plan covers Monday-Friday (workweek catering). Each day gets
one recommended meal chosen from the available menu, respecting user
preferences, budget constraints, and variety across the week.
"""

from typing import Any

from plateful.tools.recommendation_tools import rank_items

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def generate_meal_plan(
    items: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    constraints: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Auto-generate a 5-day meal plan using ranked items.

    The algorithm picks the top-scored item for each day, then removes
    it from the pool so subsequent days get different meals (variety).

    Returns a dict keyed by day name, e.g.::

        {"Monday": {"name": "Salmon Poke Bowl", ...}, ...}
    """
    if not items:
        return {day: {} for day in WEEKDAYS}

    ranked = rank_items(items, profile)
    pool = list(ranked)
    plan: dict[str, dict[str, Any]] = {}

    for day in WEEKDAYS:
        if pool:
            pick = pool.pop(0)
            plan[day] = {
                "name": pick.get("name", ""),
                "price_usd": pick.get("price_usd"),
                "category": pick.get("category", ""),
                "cuisine": pick.get("cuisine", ""),
                "calories": pick.get("calories"),
                "description": pick.get("description", ""),
                "score": pick.get("score", 0),
            }
        else:
            # Fewer items than days — cycle back to the top
            ranked_copy = rank_items(items, profile)
            pick = ranked_copy[0] if ranked_copy else {}
            plan[day] = {
                "name": pick.get("name", ""),
                "price_usd": pick.get("price_usd"),
                "category": pick.get("category", ""),
                "cuisine": pick.get("cuisine", ""),
                "calories": pick.get("calories"),
                "description": pick.get("description", ""),
                "score": pick.get("score", 0),
            }

    return plan


def swap_day(
    plan: dict[str, dict[str, Any]],
    day: str,
    new_item: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Replace a single day's meal in an existing plan.

    Returns the updated plan. The old item is stored in an ``old_item``
    key on the new day entry so callers can log the swap event.
    """
    normalised = day.capitalize()
    if normalised not in WEEKDAYS:
        return plan

    old = plan.get(normalised, {})
    plan[normalised] = {
        "name": new_item.get("name", ""),
        "price_usd": new_item.get("price_usd"),
        "category": new_item.get("category", ""),
        "cuisine": new_item.get("cuisine", ""),
        "calories": new_item.get("calories"),
        "description": new_item.get("description", ""),
        "old_item": old.get("name", ""),
    }
    return plan


def format_meal_plan_text(plan: dict[str, dict[str, Any]]) -> str:
    """Format a meal plan dict into a human-readable string."""
    lines = ["Here's your meal plan for the week:\n"]
    total = 0.0

    for day in WEEKDAYS:
        entry = plan.get(day, {})
        name = entry.get("name", "—")
        price = entry.get("price_usd")
        cuisine = entry.get("cuisine", "")
        calories = entry.get("calories")

        price_str = f"${price}" if price is not None else ""
        cal_str = f", {calories} cal" if calories else ""
        cuisine_str = f" ({cuisine}{cal_str})" if cuisine else ""

        lines.append(f"**{day}**: {name} {price_str}{cuisine_str}")
        if price is not None:
            total += float(price)

    lines.append(f"\n**Weekly total**: ${total:.2f}")
    return "\n".join(lines)


def meal_plan_summary(plan: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return a compact summary of the plan for API responses."""
    total = sum(float(e.get("price_usd", 0) or 0) for e in plan.values())
    return {
        "days": {
            day: {
                "name": entry.get("name", ""),
                "price_usd": entry.get("price_usd"),
                "cuisine": entry.get("cuisine", ""),
                "calories": entry.get("calories"),
            }
            for day, entry in plan.items()
        },
        "total_usd": round(total, 2),
        "day_count": len([d for d in plan.values() if d.get("name")]),
    }
