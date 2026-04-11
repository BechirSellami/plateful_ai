"""Meal Plan Agent: generates and edits weekly meal plans.

Supports two operations:
- **generate**: auto-creates a Mon-Fri plan from menu items + user prefs
- **swap**: replaces a single day's meal (user says "swap Monday for pasta")

The agent stores the active plan on ``state.meal_plan`` so it persists
across turns within the same session.
"""

from typing import Any, ClassVar

import structlog

from plateful.core.config import settings
from plateful.core.workflow import WorkflowState
from plateful.tools.mealplan_tools import (
    WEEKDAYS,
    format_meal_plan_text,
    generate_meal_plan,
    swap_day,
)

logger = structlog.get_logger()

MEALPLAN_SYSTEM_PROMPT = """You are the Meal Plan Agent for a corporate catering service.
You have generated a weekly meal plan (Monday-Friday) for the employee.

Present the plan in a friendly, concise format. For each day show:
- The meal name and price
- A brief reason it was chosen (e.g. matches their cuisine preference, adds variety)

After the plan, show the weekly total and invite the user to swap any day they'd like.
Keep it short — no more than 2 sentences per day.

If the user is swapping a day, acknowledge the change and show the updated plan.
"""


class MealPlanAgent:
    """Generate or edit a weekly meal plan."""

    def __init__(self, anthropic_client: Any | None = None) -> None:
        self._client = anthropic_client

    async def run(self, state: WorkflowState) -> WorkflowState:
        """Entry point — detect whether to generate or swap."""
        # Check if this is a swap request (only when a plan already exists)
        if state.meal_plan:
            swap_info = self._detect_swap(state)
            if swap_info:
                return await self._handle_swap(state, swap_info)

        return await self._handle_generate(state)

    # --- Generate -------------------------------------------------------------

    async def _handle_generate(self, state: WorkflowState) -> WorkflowState:
        """Generate a fresh weekly meal plan."""
        items = state.menu_items
        profile = state.user_profile
        constraints = state.constraints

        plan = generate_meal_plan(items, profile, constraints=constraints)
        state.meal_plan = plan

        # Try LLM for natural language presentation
        plan_text = await self._generate_llm_text(plan, profile, state=state)
        if not plan_text:
            plan_text = format_meal_plan_text(plan)

        state.recommendation_text = plan_text
        state.last_result = plan_text

        logger.info(
            "mealplan_generated",
            trace_id=state.trace_id,
            days=len([d for d in plan.values() if d.get("name")]),
        )

        return state

    # --- Swap -----------------------------------------------------------------

    async def _handle_swap(
        self,
        state: WorkflowState,
        swap_info: dict[str, str],
    ) -> WorkflowState:
        """Replace one day's meal in the existing plan."""
        day = swap_info["day"]
        new_item_name = swap_info.get("item", "")

        # Resolve the new item from the menu, excluding items already in the plan
        plan_item_names = {
            entry.get("name", "").lower() for entry in state.meal_plan.values()
        }
        available = [
            item
            for item in state.menu_items
            if item.get("name", "").lower() not in plan_item_names
        ]

        new_item = self._resolve_item(new_item_name, available)
        # Fall back to full menu if not found in filtered list
        if not new_item:
            new_item = self._resolve_item(new_item_name, state.menu_items)

        if not new_item:
            state.recommendation_text = (
                f'I couldn\'t find "{new_item_name}" on today\'s menu. '
                "Could you try a different item?"
            )
            state.last_result = state.recommendation_text
            return state

        old_name = state.meal_plan.get(day.capitalize(), {}).get("name", "")
        state.meal_plan = swap_day(state.meal_plan, day, new_item)

        # Build swap event for learning agent
        state.last_result = {
            "event_type": "mealplan_edited",
            "payload": {
                "day": day,
                "old_item": old_name,
                "new_item": new_item.get("name", ""),
            },
        }

        # Present updated plan
        plan_text = format_meal_plan_text(state.meal_plan)
        swap_msg = (
            f"Done! I've swapped **{day}** from {old_name} "
            f"to **{new_item['name']}**.\n\n"
        )
        state.recommendation_text = swap_msg + plan_text

        logger.info(
            "mealplan_swapped",
            trace_id=state.trace_id,
            day=day,
            old_item=old_name,
            new_item=new_item.get("name", ""),
        )

        return state

    # --- Helpers --------------------------------------------------------------

    _SWAP_TRIGGERS: ClassVar[list[str]] = ["swap", "change", "replace", "switch", "update"]

    def _detect_swap(self, state: WorkflowState) -> dict[str, str] | None:
        """Detect a swap request against the active meal plan.

        Handles patterns like:
        - "swap Monday for Salmon Poke Bowl"
        - "change Tuesday to pasta"
        - "replace the tofu with something else"
        - "update the meal plan with Pad Thai"
        - "Not a big fan of tofu, can we swap it?"
        """
        msg = ""
        if state.messages:
            msg = state.messages[-1].get("content", "").lower()

        if not any(trigger in msg for trigger in self._SWAP_TRIGGERS):
            return None

        # --- Determine which day to swap ---
        # Strategy 1: explicit day name
        day = None
        for d in WEEKDAYS:
            if d.lower() in msg:
                day = d
                break

        # Strategy 2: match an item name from the current plan
        if not day and state.meal_plan:
            for plan_day, entry in state.meal_plan.items():
                item_name = entry.get("name", "").lower()
                if not item_name:
                    continue
                # Check if any significant word from the plan item appears in the message
                item_words = {w for w in item_name.split() if len(w) > 2}
                if any(w in msg for w in item_words):
                    day = plan_day
                    break

        if not day:
            return None

        # --- Extract the new item ---
        item = ""
        for sep in [" for ", " to ", " with "]:
            if sep in msg:
                item = msg.split(sep, 1)[1].strip().rstrip(".!?")
                break

        return {"day": day, "item": item}

    def _resolve_item(self, name: str, menu_items: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Find a menu item by name (fuzzy)."""
        if not name:
            return None

        name_lower = name.lower()

        # Exact substring match
        for item in menu_items:
            if name_lower in item.get("name", "").lower():
                return item

        # Word-level match
        search_words = {w for w in name_lower.split() if len(w) > 2}
        for item in menu_items:
            item_lower = item.get("name", "").lower()
            if any(w in item_lower for w in search_words):
                return item

        # Cuisine/category match (e.g. "something Italian")
        for item in menu_items:
            if name_lower in item.get("cuisine", "").lower():
                return item
            if name_lower in item.get("category", "").lower():
                return item

        return None

    async def _generate_llm_text(
        self,
        plan: dict[str, dict[str, Any]],
        profile: dict[str, Any],
        *,
        state: WorkflowState | None = None,
    ) -> str | None:
        """Use Claude to present the meal plan in natural language."""
        if not self._client or not settings.anthropic_api_key:
            return None

        try:
            from plateful.core.observability import null_llm_trace, trace_llm_call

            plan_text = format_meal_plan_text(plan)

            profile_text = ""
            if profile.get("preferences"):
                profile_text += f"\nPreferences: {', '.join(profile['preferences'])}"
            if profile.get("dietary_restrictions"):
                profile_text += (
                    f"\nDietary restrictions: {', '.join(profile['dietary_restrictions'])}"
                )

            prompt = f"""User profile:{profile_text or " No profile data yet"}

Generated meal plan:
{plan_text}

Present this plan to the user in a friendly way. Explain briefly why each \
day's pick is a good fit. End by inviting them to swap any day."""

            tracing = getattr(state, "_tracing", None) if state else None
            model = "claude-sonnet-4-20250514"

            if tracing is not None and tracing.is_active:
                gen_ctx = trace_llm_call(
                    tracing, name="mealplan.llm", model=model, input_data=prompt
                )
            else:
                gen_ctx = null_llm_trace()

            async with gen_ctx as gen:
                response = await self._client.messages.create(
                    model=model,
                    system=MEALPLAN_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=768,
                )
                gen.update(
                    output=response.content[0].text if response.content else "",
                    usage_details={
                        "input": response.usage.input_tokens,
                        "output": response.usage.output_tokens,
                    },
                ).end()

            for block in response.content:
                if block.type == "text":
                    return block.text  # type: ignore[no-any-return]

        except Exception:
            logger.exception("llm_mealplan_failed")

        return None
