"""Unit tests for meal plan tools."""

import pytest

from plateful.tools.mealplan_tools import (
    WEEKDAYS,
    format_meal_plan_text,
    generate_meal_plan,
    meal_plan_summary,
    swap_day,
)

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


# ---------------------------------------------------------------------------
# generate_meal_plan
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGenerateMealPlan:
    def test_returns_five_days(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        assert set(plan.keys()) == set(WEEKDAYS)

    def test_each_day_has_a_name(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        for day in WEEKDAYS:
            assert plan[day]["name"], f"Missing name for {day}"

    def test_no_duplicate_meals(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        names = [plan[d]["name"] for d in WEEKDAYS]
        assert len(names) == len(set(names)), f"Duplicates found: {names}"

    def test_respects_user_preferences(self) -> None:
        profile = {"favorite_cuisines": ["japanese"], "preferences": ["salmon"]}
        plan = generate_meal_plan(SAMPLE_ITEMS, profile)
        # The top-ranked item (Japanese + salmon match) should be Monday
        assert plan["Monday"]["cuisine"] == "japanese"

    def test_empty_items_returns_empty_days(self) -> None:
        plan = generate_meal_plan([], {})
        for day in WEEKDAYS:
            assert plan[day] == {}

    def test_fewer_items_than_days(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS[:3], {})
        # Should still produce 5 days (cycles back)
        for day in WEEKDAYS:
            assert plan[day]["name"]


# ---------------------------------------------------------------------------
# swap_day
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSwapDay:
    def test_replaces_correct_day(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        old_tuesday = plan["Tuesday"]["name"]
        new_item = {"name": "Burger Deluxe", "price_usd": 17, "cuisine": "american"}

        updated = swap_day(plan, "Tuesday", new_item)
        assert updated["Tuesday"]["name"] == "Burger Deluxe"
        assert updated["Tuesday"]["old_item"] == old_tuesday

    def test_other_days_unchanged(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        monday_before = plan["Monday"]["name"]
        new_item = {"name": "Pad Thai", "price_usd": 14}

        swap_day(plan, "Wednesday", new_item)
        assert plan["Monday"]["name"] == monday_before

    def test_invalid_day_returns_unchanged(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        original = dict(plan)
        swap_day(plan, "Saturday", {"name": "Test"})
        assert plan.keys() == original.keys()

    def test_case_insensitive(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        swap_day(plan, "monday", {"name": "Pad Thai", "price_usd": 14})
        assert plan["Monday"]["name"] == "Pad Thai"


# ---------------------------------------------------------------------------
# format_meal_plan_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFormatMealPlanText:
    def test_contains_all_days(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        text = format_meal_plan_text(plan)
        for day in WEEKDAYS:
            assert day in text

    def test_contains_weekly_total(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        text = format_meal_plan_text(plan)
        assert "Weekly total" in text
        assert "$" in text

    def test_contains_prices(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        text = format_meal_plan_text(plan)
        assert "$" in text


# ---------------------------------------------------------------------------
# meal_plan_summary
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMealPlanSummary:
    def test_returns_correct_structure(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        summary = meal_plan_summary(plan)
        assert "days" in summary
        assert "total_usd" in summary
        assert "day_count" in summary
        assert summary["day_count"] == 5

    def test_total_is_sum_of_prices(self) -> None:
        plan = generate_meal_plan(SAMPLE_ITEMS, {})
        summary = meal_plan_summary(plan)
        expected = sum(float(plan[d].get("price_usd", 0) or 0) for d in WEEKDAYS)
        assert summary["total_usd"] == round(expected, 2)
