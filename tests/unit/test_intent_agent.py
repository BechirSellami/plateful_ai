import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from plateful.agents.intent import IntentAgent
from plateful.core.workflow import WorkflowState


def _make_state(message: str, **kwargs: Any) -> WorkflowState:
    return WorkflowState(
        user_id="emp_123",
        session_id="s",
        messages=[{"content": message}] if message else [],
        **kwargs,
    )


# ---------------------------------------------------------------------------
# Keyword mode (default)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIntentAgentKeyword:
    async def test_classifies_order_intent(self) -> None:
        result = await IntentAgent().run(_make_state("I want to order lunch"))
        assert result.intent == "order_meal"

    async def test_classifies_recommendation_intent(self) -> None:
        result = await IntentAgent().run(_make_state("Can you recommend something healthy?"))
        assert result.intent == "get_recommendation"

    async def test_classifies_mealplan_intent(self) -> None:
        result = await IntentAgent().run(_make_state("Create a meal plan for the week"))
        assert result.intent == "create_mealplan"

    async def test_classifies_preference_intent(self) -> None:
        result = await IntentAgent().run(_make_state("I'm allergic to peanuts"))
        assert result.intent == "declare_preference"

    async def test_defaults_to_recommendation(self) -> None:
        result = await IntentAgent().run(_make_state("hello"))
        assert result.intent == "get_recommendation"

    async def test_extracts_budget_constraint(self) -> None:
        result = await IntentAgent().run(_make_state("Order lunch under $25"))
        assert result.constraints["budget"] == 25

    async def test_extracts_meal_type(self) -> None:
        result = await IntentAgent().run(_make_state("Get me dinner"))
        assert result.constraints["meal_type"] == "dinner"

    async def test_extracts_dietary_constraint(self) -> None:
        result = await IntentAgent().run(_make_state("I want something vegan"))
        assert result.constraints["dietary"] == "vegan"

    async def test_extracts_cuisine_constraint(self) -> None:
        result = await IntentAgent().run(_make_state("Recommend thai food"))
        assert result.constraints["cuisine"] == "thai"

    async def test_handles_empty_messages(self) -> None:
        state = WorkflowState(user_id="emp_123", session_id="s")
        result = await IntentAgent().run(state)
        assert result.intent == "get_recommendation"

    async def test_preserves_existing_constraints(self) -> None:
        result = await IntentAgent().run(
            _make_state("Order lunch under $20", constraints={"existing_key": "value"})
        )
        assert result.constraints["existing_key"] == "value"
        assert result.constraints["budget"] == 20

    async def test_classifies_confirm_order_ill_take(self) -> None:
        result = await IntentAgent().run(_make_state("I'll take the Grilled Chicken Bowl"))
        assert result.intent == "confirm_order"

    async def test_classifies_confirm_order_go_with(self) -> None:
        result = await IntentAgent().run(_make_state("Go with the first one"))
        assert result.intent == "confirm_order"

    async def test_classifies_confirm_order_sounds_good(self) -> None:
        result = await IntentAgent().run(_make_state("Sounds good, order it"))
        assert result.intent == "confirm_order"

    async def test_classifies_confirm_order_that_one(self) -> None:
        result = await IntentAgent().run(_make_state("That one please"))
        assert result.intent == "confirm_order"

    async def test_confirm_order_before_order_meal(self) -> None:
        """'order the' should match confirm_order, not order_meal."""
        result = await IntentAgent().run(_make_state("Order the Salmon Poke Bowl"))
        assert result.intent == "confirm_order"

    async def test_mode_defaults_to_keyword(self) -> None:
        agent = IntentAgent()
        assert agent.mode == "keyword"


# ---------------------------------------------------------------------------
# LLM mode
# ---------------------------------------------------------------------------


def _mock_anthropic_response(payload: dict[str, Any]) -> AsyncMock:
    """Create a mock AsyncAnthropic client that returns *payload* as JSON."""
    text_block = MagicMock()
    text_block.text = json.dumps(payload)
    text_block.type = "text"

    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = "end_turn"

    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


@pytest.mark.unit
class TestIntentAgentLLM:
    async def test_llm_classifies_intent(self) -> None:
        client = _mock_anthropic_response({"intent": "order_meal", "constraints": {"budget": 30}})
        agent = IntentAgent(mode="llm", anthropic_client=client)

        result = await agent.run(_make_state("I'd like to order something under $30"))

        assert result.intent == "order_meal"
        assert result.constraints["budget"] == 30
        client.messages.create.assert_awaited_once()

    async def test_llm_extracts_multiple_constraints(self) -> None:
        client = _mock_anthropic_response(
            {
                "intent": "get_recommendation",
                "constraints": {"dietary": "vegan", "cuisine": "thai", "budget": 15},
            }
        )
        agent = IntentAgent(mode="llm", anthropic_client=client)

        result = await agent.run(_make_state("Suggest a vegan thai dish under $15"))

        assert result.intent == "get_recommendation"
        assert result.constraints == {"dietary": "vegan", "cuisine": "thai", "budget": 15}

    async def test_llm_invalid_intent_defaults(self) -> None:
        client = _mock_anthropic_response({"intent": "do_a_dance", "constraints": {}})
        agent = IntentAgent(mode="llm", anthropic_client=client)

        result = await agent.run(_make_state("Do a dance"))

        assert result.intent == "get_recommendation"

    async def test_llm_falls_back_on_api_error(self) -> None:
        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
        agent = IntentAgent(mode="llm", anthropic_client=client)

        result = await agent.run(_make_state("I want to order lunch"))

        # Falls back to keyword classification
        assert result.intent == "order_meal"

    async def test_llm_falls_back_on_invalid_json(self) -> None:
        text_block = MagicMock()
        text_block.text = "not json at all"
        text_block.type = "text"
        response = MagicMock()
        response.content = [text_block]

        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=response)
        agent = IntentAgent(mode="llm", anthropic_client=client)

        result = await agent.run(_make_state("Order dinner"))

        # Falls back to keyword classification
        assert result.intent == "order_meal"

    async def test_llm_mode_without_client_uses_keyword(self) -> None:
        agent = IntentAgent(mode="llm", anthropic_client=None)

        result = await agent.run(_make_state("I want to order lunch"))

        # No client → keyword fallback path
        assert result.intent == "order_meal"

    async def test_llm_bad_constraints_type_ignored(self) -> None:
        client = _mock_anthropic_response({"intent": "order_meal", "constraints": "not a dict"})
        agent = IntentAgent(mode="llm", anthropic_client=client)

        result = await agent.run(_make_state("Order lunch"))

        assert result.intent == "order_meal"
        assert result.constraints == {}

    async def test_llm_classifies_confirm_order_with_selected_item(self) -> None:
        client = _mock_anthropic_response(
            {
                "intent": "confirm_order",
                "constraints": {"selected_item": "Grilled Chicken Bowl"},
            }
        )
        agent = IntentAgent(mode="llm", anthropic_client=client)

        result = await agent.run(_make_state("I'll take the Grilled Chicken Bowl"))

        assert result.intent == "confirm_order"
        assert result.constraints["selected_item"] == "Grilled Chicken Bowl"

    async def test_preserves_existing_constraints_in_llm_mode(self) -> None:
        client = _mock_anthropic_response({"intent": "order_meal", "constraints": {"budget": 20}})
        agent = IntentAgent(mode="llm", anthropic_client=client)

        result = await agent.run(
            _make_state("Order lunch under $20", constraints={"existing_key": "value"})
        )

        assert result.constraints["existing_key"] == "value"
        assert result.constraints["budget"] == 20
