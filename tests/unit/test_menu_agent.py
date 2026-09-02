import pytest

from plateful.agents.menu import MenuAgent
from plateful.core.workflow import WorkflowState

SAMPLE_MENU = [
    {
        "id": "1",
        "name": "Grilled Chicken Bowl",
        "price_usd": 18.50,
        "category": "healthy",
        "cuisine": "thai",
        "calories": 450,
        "allergens": ["soy"],
        "active": True,
    },
    {
        "id": "2",
        "name": "Pasta Carbonara",
        "price_usd": 22.00,
        "category": "comfort",
        "cuisine": "italian",
        "calories": 750,
        "allergens": ["dairy", "eggs", "gluten"],
        "active": True,
    },
    {
        "id": "3",
        "name": "Shrimp Tacos",
        "price_usd": 15.00,
        "category": "light",
        "cuisine": "mexican",
        "calories": 380,
        "allergens": ["shellfish", "gluten"],
        "active": True,
    },
    {
        "id": "4",
        "name": "Tofu Stir Fry",
        "price_usd": 14.00,
        "category": "healthy",
        "cuisine": "thai",
        "calories": 350,
        "allergens": ["soy"],
        "active": True,
    },
    {
        "id": "5",
        "name": "Inactive Burger",
        "price_usd": 12.00,
        "category": "comfort",
        "cuisine": "american",
        "calories": 800,
        "allergens": ["gluten", "dairy"],
        "active": False,
    },
]


@pytest.mark.unit
class TestMenuAgent:
    async def test_returns_all_active_items_without_constraints(self) -> None:
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(user_id="emp_123", session_id="s")

        result = await agent.run(state)

        assert len(result.menu_items) == 4  # excludes inactive
        names = [i["name"] for i in result.menu_items]
        assert "Inactive Burger" not in names

    async def test_filters_by_budget_constraint(self) -> None:
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"budget": 16},
        )

        result = await agent.run(state)

        for item in result.menu_items:
            assert item["price_usd"] <= 16

    async def test_filters_by_cuisine_constraint(self) -> None:
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"cuisine": "thai"},
        )

        result = await agent.run(state)

        for item in result.menu_items:
            assert item["cuisine"] == "thai"

    async def test_filters_by_cuisine_umbrella_group(self) -> None:
        """Regression test for the reported bug: 'asian' returned zero
        items because no seed item is tagged literally 'asian' — it needs
        to match via the thai/chinese/japanese/... group."""
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"cuisine": "asian"},
        )

        result = await agent.run(state)

        names = [i["name"] for i in result.menu_items]
        assert names  # not empty
        for item in result.menu_items:
            assert item["cuisine"] in {"thai", "chinese", "japanese", "indian"}

    async def test_removes_allergen_items(self) -> None:
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            user_profile={"allergies": ["Allergic to shellfish"]},
        )

        result = await agent.run(state)

        names = [i["name"] for i in result.menu_items]
        assert "Shrimp Tacos" not in names

    async def test_removes_dairy_allergen(self) -> None:
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            user_profile={"allergies": ["Avoids dairy due to intolerance"]},
        )

        result = await agent.run(state)

        names = [i["name"] for i in result.menu_items]
        assert "Pasta Carbonara" not in names

    async def test_removes_allergen_declared_in_current_message(self) -> None:
        """Regression test: a same-turn 'I'm allergic to X, order me Y'
        must be protected immediately. It previously wasn't — the filter
        only read state.user_profile (persisted, prior-turn data), so a
        first-time allergy declaration had zero effect on that same
        turn's menu filtering, regardless of what the planner extracted
        into constraints."""
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[
                {
                    "role": "user",
                    "content": "I'm allergic to shellfish and want to order asian today",
                }
            ],
            # No persisted profile — this is the user's first mention.
            user_profile={},
        )

        result = await agent.run(state)

        names = [i["name"] for i in result.menu_items]
        assert "Shrimp Tacos" not in names

    async def test_combines_persisted_and_current_message_allergens(self) -> None:
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"role": "user", "content": "and I'm also allergic to dairy"}],
            user_profile={"allergies": ["Allergic to shellfish"]},
        )

        result = await agent.run(state)

        names = [i["name"] for i in result.menu_items]
        assert "Shrimp Tacos" not in names  # from persisted profile
        assert "Pasta Carbonara" not in names  # from this message

    async def test_combined_budget_and_allergen_filter(self) -> None:
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"budget": 20},
            user_profile={"allergies": ["Allergic to soy"]},
        )

        result = await agent.run(state)

        for item in result.menu_items:
            assert item["price_usd"] <= 20
            assert "soy" not in [a.lower() for a in item.get("allergens", [])]

    async def test_sets_last_result(self) -> None:
        agent = MenuAgent(menu_data=SAMPLE_MENU)
        state = WorkflowState(user_id="emp_123", session_id="s")

        result = await agent.run(state)

        assert result.last_result == result.menu_items

    async def test_empty_menu(self) -> None:
        agent = MenuAgent(menu_data=[])
        state = WorkflowState(user_id="emp_123", session_id="s")

        result = await agent.run(state)

        assert result.menu_items == []
