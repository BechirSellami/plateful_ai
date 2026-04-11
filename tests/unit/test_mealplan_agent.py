"""Unit tests for the MealPlan Agent."""

from typing import Any
from unittest.mock import patch

import pytest

from plateful.agents.mealplan import MealPlanAgent
from plateful.core.workflow import WorkflowState
from plateful.tools.mealplan_tools import WEEKDAYS

SAMPLE_ITEMS = [
    {
        "name": "Salmon Poke Bowl",
        "price_usd": 16,
        "category": "healthy",
        "cuisine": "japanese",
        "calories": 520,
        "description": "Fresh salmon",
    },
    {
        "name": "Tofu Stir Fry",
        "price_usd": 13,
        "category": "healthy",
        "cuisine": "chinese",
        "calories": 380,
        "description": "Crispy tofu",
    },
    {
        "name": "Grilled Chicken Bowl",
        "price_usd": 15,
        "category": "healthy",
        "cuisine": "mediterranean",
        "calories": 490,
        "description": "Herb chicken",
    },
    {
        "name": "Lentil Soup",
        "price_usd": 11,
        "category": "light",
        "cuisine": "indian",
        "calories": 310,
        "description": "Warming lentils",
    },
    {
        "name": "Caesar Salad",
        "price_usd": 12,
        "category": "light",
        "cuisine": "italian",
        "calories": 350,
        "description": "Classic caesar",
    },
    {
        "name": "Burger Deluxe",
        "price_usd": 17,
        "category": "comfort",
        "cuisine": "american",
        "calories": 720,
        "description": "Juicy burger",
    },
    {
        "name": "Pad Thai",
        "price_usd": 14,
        "category": "comfort",
        "cuisine": "thai",
        "calories": 580,
        "description": "Rice noodles",
    },
]


def _make_state(message: str, *, items: list[dict[str, Any]] | None = None) -> WorkflowState:
    state = WorkflowState(
        user_id="emp_123",
        session_id="sess_1",
        messages=[{"content": message}],
    )
    state.menu_items = items if items is not None else list(SAMPLE_ITEMS)
    return state


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMealPlanGenerate:
    async def test_generates_five_day_plan(self) -> None:
        agent = MealPlanAgent()
        state = _make_state("Plan my meals for the week")

        state = await agent.run(state)

        assert state.meal_plan
        assert set(state.meal_plan.keys()) == set(WEEKDAYS)
        for day in WEEKDAYS:
            assert state.meal_plan[day].get("name")

    async def test_sets_recommendation_text(self) -> None:
        agent = MealPlanAgent()
        state = _make_state("Plan my meals for the week")

        state = await agent.run(state)

        assert state.recommendation_text is not None
        assert "Monday" in state.recommendation_text
        assert "Weekly total" in state.recommendation_text

    async def test_no_duplicates_across_days(self) -> None:
        agent = MealPlanAgent()
        state = _make_state("Plan my week")

        state = await agent.run(state)

        names = [state.meal_plan[d]["name"] for d in WEEKDAYS]
        assert len(names) == len(set(names))

    async def test_empty_menu_produces_empty_plan(self) -> None:
        agent = MealPlanAgent()
        state = _make_state("Plan my week", items=[])

        state = await agent.run(state)

        for day in WEEKDAYS:
            assert state.meal_plan[day] == {}

    async def test_respects_user_profile(self) -> None:
        agent = MealPlanAgent()
        state = _make_state("Plan my meals for the week")
        state.user_profile = {"favorite_cuisines": ["japanese"], "preferences": ["salmon"]}

        state = await agent.run(state)

        # Japanese item should be highly ranked → Monday
        assert state.meal_plan["Monday"]["cuisine"] == "japanese"


# ---------------------------------------------------------------------------
# Swap
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMealPlanSwap:
    async def test_swap_replaces_day(self) -> None:
        agent = MealPlanAgent()
        state = _make_state("Plan my week")
        state = await agent.run(state)

        # Now swap Tuesday
        state.messages = [{"content": "Swap Tuesday for Pad Thai"}]
        state = await agent.run(state)

        assert state.meal_plan["Tuesday"]["name"] == "Pad Thai"

    async def test_swap_preserves_other_days(self) -> None:
        agent = MealPlanAgent()
        state = _make_state("Plan my week")
        state = await agent.run(state)

        monday_before = state.meal_plan["Monday"]["name"]

        state.messages = [{"content": "Change Wednesday to Burger Deluxe"}]
        state = await agent.run(state)

        assert state.meal_plan["Monday"]["name"] == monday_before

    async def test_swap_logs_event(self) -> None:
        agent = MealPlanAgent()
        state = _make_state("Plan my week")
        state = await agent.run(state)

        state.messages = [{"content": "Swap Monday for Lentil Soup"}]
        state = await agent.run(state)

        assert isinstance(state.last_result, dict)
        assert state.last_result["event_type"] == "mealplan_edited"
        assert state.last_result["payload"]["new_item"] == "Lentil Soup"

    async def test_swap_unknown_item_shows_error(self) -> None:
        agent = MealPlanAgent()
        state = _make_state("Plan my week")
        state = await agent.run(state)

        state.messages = [{"content": "Swap Monday for Unicorn Steak"}]
        state = await agent.run(state)

        assert "couldn't find" in state.recommendation_text.lower()

    async def test_swap_without_plan_generates_fresh(self) -> None:
        """If no plan exists yet, generate instead of swapping."""
        agent = MealPlanAgent()
        state = _make_state("Swap Monday for Pad Thai")
        # No prior plan — should fall through to generate

        state = await agent.run(state)

        # Should have generated a full plan (not swapped)
        assert set(state.meal_plan.keys()) == set(WEEKDAYS)

    async def test_swap_by_item_name_without_day(self) -> None:
        """User says 'swap the tofu for Pad Thai' — should find the day by item."""
        agent = MealPlanAgent()
        state = _make_state("Plan my week")
        state = await agent.run(state)

        # Find which day has "Tofu Stir Fry" in the plan
        tofu_day = None
        for day in WEEKDAYS:
            if "tofu" in state.meal_plan[day].get("name", "").lower():
                tofu_day = day
                break
        assert tofu_day is not None, "Tofu should be in the plan"

        state.messages = [{"content": "swap the tofu for Pad Thai"}]
        state = await agent.run(state)

        assert state.meal_plan[tofu_day]["name"] == "Pad Thai"

    async def test_update_meal_plan_with_item(self) -> None:
        """User says 'Update the meal plan with Pad Thai' — should swap matched item."""
        agent = MealPlanAgent()
        state = _make_state("Plan my week")
        state = await agent.run(state)

        # "update" triggers swap detection, "Pad Thai" is the new item
        # But we need a reference to an old item — let's use a specific item
        # The plan has items; pick one to reference
        thursday_item = state.meal_plan["Thursday"]["name"]
        state.messages = [
            {"content": f"update the meal plan, replace the {thursday_item} with Pad Thai"}
        ]
        state = await agent.run(state)

        assert state.meal_plan["Thursday"]["name"] == "Pad Thai"


# ---------------------------------------------------------------------------
# Integration: planner routes to mealplan agent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMealPlanRouting:
    async def test_keyword_planner_routes_mealplan(self) -> None:
        from plateful.agents.planner import PlannerAgent

        planner = PlannerAgent(mode="keyword")
        state = WorkflowState(
            user_id="emp_1",
            session_id="s1",
            messages=[{"content": "Plan my meals for the week"}],
        )
        result = await planner.plan(state, {"memory", "menu", "mealplan", "recommendation"})

        assert result["intent"] == "create_mealplan"
        agents = [s["agent"] for s in result["plan"]]
        assert "mealplan" in agents
        assert "recommendation" not in agents

    async def test_orchestrator_runs_mealplan(self) -> None:
        from plateful.agents.planner import PlannerAgent
        from plateful.core.orchestrator import run_planned_workflow

        class FakeMenu:
            async def run(self, state: WorkflowState) -> WorkflowState:
                state.menu_items = list(SAMPLE_ITEMS)
                return state

        agent = MealPlanAgent()
        registry: dict[str, Any] = {
            "menu": FakeMenu(),
            "mealplan": agent,
        }
        planner = PlannerAgent(mode="keyword")
        state = WorkflowState(
            user_id="emp_1",
            session_id="s1",
            messages=[{"content": "Plan my meals for the week"}],
        )

        with patch("plateful.core.observability.get_langfuse", return_value=None):
            state = await run_planned_workflow(state, registry, planner)

        assert state.intent == "create_mealplan"
        assert state.meal_plan
        assert len(state.meal_plan) == 5
        assert state.recommendation_text is not None
