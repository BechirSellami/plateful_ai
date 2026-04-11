from decimal import Decimal
from typing import Any


async def get_menu(
    filters: dict[str, Any] | None = None,
    menu_data: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch available menu items, optionally filtered by category, cuisine, budget, or time."""
    items = menu_data or []
    if not filters:
        return [item for item in items if item.get("active", True)]

    result = []
    for item in items:
        if not item.get("active", True):
            continue
        if "category" in filters and item.get("category") != filters["category"]:
            continue
        if "cuisine" in filters and item.get("cuisine") != filters["cuisine"]:
            continue
        if "max_price" in filters and Decimal(str(item.get("price_usd", 0))) > Decimal(
            str(filters["max_price"])
        ):
            continue
        if "max_calories" in filters and (item.get("calories") or 0) > filters["max_calories"]:
            continue
        result.append(item)
    return result


def check_allergens(
    items: list[dict[str, Any]],
    user_allergens: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Filter out items containing any of the user's declared allergens.

    This is a deterministic safety filter — never delegated to LLM reasoning.

    Returns:
        A tuple of (safe_items, removed_items). Each removed item gets a
        ``matched_allergens`` key listing which allergens caused removal.
    """
    if not user_allergens:
        return items, []

    allergen_set = {a.lower() for a in user_allergens}
    safe_items: list[dict[str, Any]] = []
    removed_items: list[dict[str, Any]] = []

    for item in items:
        item_allergens = {a.lower() for a in item.get("allergens", [])}
        matched = item_allergens & allergen_set
        if matched:
            removed_items.append({**item, "matched_allergens": sorted(matched)})
        else:
            safe_items.append(item)

    return safe_items, removed_items


def filter_by_availability(
    items: list[dict[str, Any]],
    current_time: str | None = None,
) -> list[dict[str, Any]]:
    """Filter menu items by current availability window."""
    if not current_time:
        return items

    available = []
    for item in items:
        avail_from = item.get("available_from")
        avail_to = item.get("available_to")
        if not avail_from or not avail_to:
            available.append(item)
            continue
        if avail_from <= current_time <= avail_to:
            available.append(item)
    return available


def get_item_details(
    item_id: str,
    menu_data: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Get detailed information about a specific menu item."""
    items = menu_data or []
    for item in items:
        if str(item.get("id")) == item_id:
            return item
    return None
