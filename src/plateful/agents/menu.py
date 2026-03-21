from typing import Any

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
        filters = self._build_filters(state)
        items = await get_menu(filters=filters, menu_data=self._menu_data)

        # Step 2: Deterministic allergen filter (safety-critical, never LLM)
        user_allergens = state.user_profile.get("allergies", [])
        # Extract allergen names from memory strings like "Allergic to peanuts"
        allergen_names = self._extract_allergen_names(user_allergens)
        items = check_allergens(items, allergen_names)

        # Step 3: Filter by availability
        items = filter_by_availability(items)

        state.menu_items = items
        state.last_result = items

        logger.info(
            "menu_agent_complete",
            trace_id=state.trace_id,
            items_found=len(items),
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

        return filters

    def _extract_allergen_names(self, allergen_memories: list[Any]) -> list[str]:
        """Extract allergen ingredient names from memory strings.

        Handles both raw strings ("peanuts") and memory objects
        ("Allergic to peanuts").
        """
        names = []
        for mem in allergen_memories:
            text = str(mem).lower()
            # Extract common allergens from memory text
            common_allergens = [
                "peanuts",
                "peanut",
                "tree nuts",
                "milk",
                "dairy",
                "eggs",
                "egg",
                "wheat",
                "gluten",
                "soy",
                "fish",
                "shellfish",
                "shrimp",
                "sesame",
            ]
            for allergen in common_allergens:
                if allergen in text:
                    names.append(allergen)
        return names
