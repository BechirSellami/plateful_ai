import re
from typing import Any, ClassVar

import structlog

from plateful.core.workflow import WorkflowState
from plateful.tools.menu_tools import check_allergens, filter_by_availability, get_menu

logger = structlog.get_logger()


class MenuAgent:
    """Fetch available items, filter by constraints (allergens, budget, time).

    The Menu Agent uses deterministic filtering for safety-critical operations
    (allergen checking) and delegates item selection reasoning to the LLM
    via the tool loop.
    """

    def __init__(self, menu_data: list[dict[str, Any]] | None = None) -> None:
        self._menu_data = menu_data or []

    async def run(self, state: WorkflowState) -> WorkflowState:
        # Step 1: Get menu items matching constraints
        filters = self._build_filters(state)  # Budget, calories, category, cuisine

        items = await get_menu(filters=filters, menu_data=self._menu_data)

        user_msg = state.messages[-1].get("content", "") if state.messages else ""

        # Step 2: Deterministic allergen filter (safety-critical, never LLM)
        # Merge PERSISTED allergies (from Memory/Mem0) with anything
        # declared in THIS message. A same-turn "I'm allergic to X, order
        # me Y" must be protected immediately — it can't wait for
        # `learning` to persist it and a future turn's Memory lookup to
        # pick it up, and it can't depend on the planner having also
        # copied the allergy into constraints.preference (it doesn't
        # always). Scanning the raw message directly is the deterministic,
        # LLM-independent path.
        user_allergens = state.user_profile.get("allergies", [])
        allergen_names = self._extract_allergen_names([*user_allergens, user_msg])

        logger.info(
            "menu_agent_start",
            trace_id=state.trace_id,
            filters=filters,
            user_allergens=user_allergens,
            extracted_allergens=allergen_names,
        )

        items, removed = check_allergens(items, allergen_names)
        logger.info(
            "menu_agent_start",
            trace_id=state.trace_id,
            items_after_allergen_filter=len(items),
            items_removed=len(removed),
        )

        # Step 2b: Detect allergen conflicts with what the user asked for
        if removed:
            conflicts = self._find_request_conflicts(user_msg.lower(), removed)
            if conflicts:
                state.allergen_conflicts = conflicts

        # Step 3: Filter by availability
        items = filter_by_availability(items)

        state.menu_items = items
        state.last_result = items

        logger.info(
            "menu_agent_complete",
            trace_id=state.trace_id,
            items_found=len(items),
            items_removed_allergens=len(removed),
            allergen_conflicts=len(state.allergen_conflicts),
            filters=filters,
            allergens_applied=len(allergen_names),
        )

        return state

    def _build_filters(self, state: WorkflowState) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        constraints = state.constraints

        if "budget" in constraints:
            filters["max_price"] = constraints["budget"]
        if "category" in constraints:
            filters["category"] = constraints["category"]
        if "cuisine" in constraints:
            filters["cuisine"] = constraints["cuisine"]
        if "max_calories" in constraints:
            filters["max_calories"] = constraints["max_calories"]
        if "food_keywords" in constraints:
            kw = constraints["food_keywords"]
            # Accept both list and comma-separated string from the LLM
            if isinstance(kw, str):
                kw = [k.strip() for k in kw.split(",") if k.strip()]
            if isinstance(kw, list) and kw:
                filters["food_keywords"] = kw

        return filters

    def _find_request_conflicts(
        self,
        user_msg: str,
        removed_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Check if any allergen-removed items match what the user asked for.

        Uses two strategies:
        1. **Allergen word match** — the user mentions an allergen ingredient
           directly (e.g. "shrimps" matches the "shellfish" allergen group).
        2. **Item name match** — a word from a removed item's name appears
           in the request (e.g. user says "pad thai", item is "Pad Thai").

        Returns a list of conflict dicts. When the match is ingredient-level,
        ``items_removed`` lists all items filtered for that allergen.
        """
        if not user_msg:
            return []

        # Allergen ingredient words that map to allergen group names.
        # Lets us detect "shrimps" -> shellfish, "peanut" -> peanuts, etc.
        ingredient_to_allergen: dict[str, str] = {
            "shrimp": "shellfish",
            "shrimps": "shellfish",
            "prawn": "shellfish",
            "prawns": "shellfish",
            "lobster": "shellfish",
            "crab": "shellfish",
            "clam": "shellfish",
            "clams": "shellfish",
            "oyster": "shellfish",
            "peanut": "peanuts",
            "peanuts": "peanuts",
            "walnut": "tree nuts",
            "almond": "tree nuts",
            "cashew": "tree nuts",
        }

        conflicts: list[dict[str, Any]] = []
        seen_allergens: set[str] = set()

        # Strategy 1: user mentions an allergen ingredient directly
        msg_words = set(user_msg.split())
        for word in msg_words:
            allergen_group = ingredient_to_allergen.get(word)
            if allergen_group and allergen_group not in seen_allergens:
                # Find all removed items that matched this allergen group
                matching_items = [
                    item.get("name", "")
                    for item in removed_items
                    if allergen_group in item.get("matched_allergens", [])
                ]
                if matching_items:
                    seen_allergens.add(allergen_group)
                    conflicts.append(
                        {
                            "ingredient": word,
                            "allergen_group": allergen_group,
                            "items_removed": matching_items,
                            "matched_allergens": [allergen_group],
                        }
                    )

        # Strategy 2: user mentions a specific item name
        for item in removed_items:
            item_name = item.get("name", "").lower()
            item_words = {w for w in item_name.split() if len(w) > 2}
            if any(w in user_msg for w in item_words):
                # Skip if already covered by strategy 1
                item_allergens = set(item.get("matched_allergens", []))
                if not item_allergens & seen_allergens:
                    conflicts.append(
                        {
                            "name": item.get("name", ""),
                            "matched_allergens": item.get("matched_allergens", []),
                        }
                    )

        return conflicts

    # Ordered longest-first so "shellfish" matches before "fish",
    # "peanuts" before "peanut", etc.
    _COMMON_ALLERGENS: ClassVar[list[str]] = [
        "tree nuts",
        "shellfish",
        "peanuts",
        "peanut",
        "gluten",
        "sesame",
        "shrimp",
        "dairy",
        "wheat",
        "milk",
        "eggs",
        "fish",
        "egg",
        "soy",
    ]

    def _extract_allergen_names(self, allergen_memories: list[Any]) -> list[str]:
        """Extract allergen ingredient names from memory strings.

        Handles both raw strings ("peanuts") and memory objects
        ("Allergic to peanuts"). Uses word-boundary matching so that
        "shellfish" does not also match "fish".
        """
        names: list[str] = []
        for mem in allergen_memories:
            text = str(mem).lower()
            for allergen in self._COMMON_ALLERGENS:
                if re.search(rf"\b{re.escape(allergen)}\b", text) and allergen not in names:
                    names.append(allergen)
        return names
