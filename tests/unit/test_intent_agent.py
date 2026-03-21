import pytest

from plateful.agents.intent import IntentAgent
from plateful.core.workflow import WorkflowState


@pytest.mark.unit
class TestIntentAgent:
    async def test_classifies_order_intent(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"content": "I want to order lunch"}],
        )

        result = await agent.run(state)

        assert result.intent == "order_meal"

    async def test_classifies_recommendation_intent(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"content": "Can you recommend something healthy?"}],
        )

        result = await agent.run(state)

        assert result.intent == "get_recommendation"

    async def test_classifies_mealplan_intent(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"content": "Create a meal plan for the week"}],
        )

        result = await agent.run(state)

        assert result.intent == "create_mealplan"

    async def test_classifies_preference_intent(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"content": "I'm allergic to peanuts"}],
        )

        result = await agent.run(state)

        assert result.intent == "declare_preference"

    async def test_defaults_to_recommendation(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"content": "hello"}],
        )

        result = await agent.run(state)

        assert result.intent == "get_recommendation"

    async def test_extracts_budget_constraint(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"content": "Order lunch under $25"}],
        )

        result = await agent.run(state)

        assert result.constraints["budget"] == 25

    async def test_extracts_meal_type(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"content": "Get me dinner"}],
        )

        result = await agent.run(state)

        assert result.constraints["meal_type"] == "dinner"

    async def test_extracts_dietary_constraint(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"content": "I want something vegan"}],
        )

        result = await agent.run(state)

        assert result.constraints["dietary"] == "vegan"

    async def test_extracts_cuisine_constraint(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"content": "Recommend thai food"}],
        )

        result = await agent.run(state)

        assert result.constraints["cuisine"] == "thai"

    async def test_handles_empty_messages(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(user_id="emp_123", session_id="s")

        result = await agent.run(state)

        assert result.intent == "get_recommendation"

    async def test_preserves_existing_constraints(self) -> None:
        agent = IntentAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"existing_key": "value"},
            messages=[{"content": "Order lunch under $20"}],
        )

        result = await agent.run(state)

        assert result.constraints["existing_key"] == "value"
        assert result.constraints["budget"] == 20
