"""Unit tests for out-of-scope intent handling."""

from typing import Any
from unittest.mock import patch

import pytest

from plateful.agents.intent import IntentAgent
from plateful.agents.planner import PlannerAgent
from plateful.core.workflow import WorkflowState


def _make_state(message: str) -> WorkflowState:
    return WorkflowState(
        user_id="emp_123",
        session_id="sess_1",
        messages=[{"content": message}],
    )


# ---------------------------------------------------------------------------
# Keyword intent classification — out_of_scope detection
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIntentOutOfScope:
    def test_weather_is_out_of_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("What's the weather like?") == "out_of_scope"

    def test_poem_is_out_of_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("Write me a poem") == "out_of_scope"

    def test_taxes_is_out_of_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("Help me with my taxes") == "out_of_scope"

    def test_joke_is_out_of_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("Tell me a joke") == "out_of_scope"

    def test_translate_is_out_of_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("Translate this to French") == "out_of_scope"

    def test_greeting_is_out_of_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("Hello there") == "out_of_scope"

    def test_food_related_stays_in_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("Any salads today?") != "out_of_scope"

    def test_hungry_stays_in_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("I'm hungry") != "out_of_scope"

    def test_price_stays_in_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("What's cheap?") != "out_of_scope"

    def test_spicy_stays_in_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("Anything spicy?") != "out_of_scope"

    def test_order_keyword_stays_in_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("Order something for me") == "order_meal"

    def test_recommend_keyword_stays_in_scope(self) -> None:
        agent = IntentAgent(mode="keyword")
        assert agent._classify_keyword("Recommend something") == "get_recommendation"


# ---------------------------------------------------------------------------
# Planner — out_of_scope produces empty plan
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlannerOutOfScope:
    async def test_keyword_planner_returns_empty_plan(self) -> None:
        planner = PlannerAgent(mode="keyword")
        state = _make_state("What's the weather?")
        result = await planner.plan(state, {"menu", "recommendation", "execution"})

        assert result["intent"] == "out_of_scope"
        assert result["plan"] == []

    async def test_keyword_planner_food_message_has_plan(self) -> None:
        planner = PlannerAgent(mode="keyword")
        state = _make_state("I'm hungry, anything good?")
        result = await planner.plan(state, {"menu", "recommendation"})

        assert result["intent"] != "out_of_scope"
        assert len(result["plan"]) > 0


# ---------------------------------------------------------------------------
# Orchestrator — out_of_scope sets recommendation_text
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrchestratorOutOfScope:
    async def test_out_of_scope_returns_helpful_message(self) -> None:
        from plateful.core.orchestrator import run_planned_workflow

        class FakeAgent:
            async def run(self, state: WorkflowState) -> WorkflowState:
                return state

        registry: dict[str, Any] = {
            "menu": FakeAgent(),
            "recommendation": FakeAgent(),
        }

        planner = PlannerAgent(mode="keyword")
        state = _make_state("What's the weather like?")

        with patch("plateful.core.observability.get_langfuse", return_value=None):
            state = await run_planned_workflow(state, registry, planner)

        assert state.intent == "out_of_scope"
        assert state.recommendation_text is not None
        assert "catering assistant" in state.recommendation_text
        assert (
            "menu" in state.recommendation_text.lower()
            or "meal" in state.recommendation_text.lower()
        )
        # No agents should have run
        assert state.menu_items == []
        assert state.recommendations == []

    async def test_in_scope_does_not_get_oos_message(self) -> None:
        from plateful.core.orchestrator import run_planned_workflow

        class FakeAgent:
            async def run(self, state: WorkflowState) -> WorkflowState:
                return state

        registry: dict[str, Any] = {
            "menu": FakeAgent(),
            "recommendation": FakeAgent(),
        }

        planner = PlannerAgent(mode="keyword")
        state = _make_state("Recommend something healthy")

        with patch("plateful.core.observability.get_langfuse", return_value=None):
            state = await run_planned_workflow(state, registry, planner)

        assert state.intent != "out_of_scope"
        # recommendation_text might be None (no real LLM), but should NOT be the OOS message
        if state.recommendation_text:
            assert "outside what I can help with" not in state.recommendation_text
