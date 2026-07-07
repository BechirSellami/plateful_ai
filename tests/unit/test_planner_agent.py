"""Unit tests for the Planner Agent."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plateful.agents.planner import AGENT_CATALOG, PlannerAgent, _build_system_prompt
from plateful.core.workflow import WorkflowState

ALL_AGENTS = {"memory", "menu", "recommendation", "execution", "learning"}


def _make_state(message: str, **kwargs: Any) -> WorkflowState:
    return WorkflowState(
        user_id="emp_123",
        session_id="s",
        messages=[{"content": message}] if message else [],
        **kwargs,
    )


def _mock_anthropic_response(payload: dict[str, Any]) -> AsyncMock:
    """Create a mock AsyncAnthropic client that returns *payload* as JSON."""
    text_block = MagicMock()
    text_block.text = json.dumps(payload)
    text_block.type = "text"

    response = MagicMock()
    response.content = [text_block]

    client = AsyncMock()
    client.messages.create = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildSystemPrompt:
    def test_includes_available_agents(self) -> None:
        prompt = _build_system_prompt({"menu", "recommendation"})
        assert "menu" in prompt
        assert "recommendation" in prompt
        assert "**execution**" not in prompt

    def test_includes_all_agents_when_all_available(self) -> None:
        prompt = _build_system_prompt(ALL_AGENTS)
        for name in AGENT_CATALOG:
            assert name in prompt


# ---------------------------------------------------------------------------
# Keyword mode (fallback)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlannerKeyword:
    async def test_order_meal_produces_recommend_flow(self) -> None:
        planner = PlannerAgent(mode="keyword")
        state = _make_state("I want to order lunch")
        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "order_meal"
        agents = [s["agent"] for s in result["plan"]]
        assert "menu" in agents
        assert "recommendation" in agents

    async def test_declare_preference_produces_learn_only(self) -> None:
        planner = PlannerAgent(mode="keyword")
        state = _make_state("I'm allergic to peanuts")
        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "declare_preference"
        agents = [s["agent"] for s in result["plan"]]
        assert "learning" in agents
        assert "menu" not in agents

    async def test_sets_state_intent_and_constraints(self) -> None:
        planner = PlannerAgent(mode="keyword")
        state = _make_state("Order lunch under $20")
        await planner.plan(state, ALL_AGENTS)

        assert state.intent == "order_meal"
        assert state.constraints["budget"] == 20

    async def test_mode_defaults_to_keyword(self) -> None:
        planner = PlannerAgent()
        assert planner.mode == "keyword"

    async def test_filters_unavailable_agents(self) -> None:
        planner = PlannerAgent(mode="keyword")
        state = _make_state("Recommend something")
        result = await planner.plan(state, {"menu", "recommendation"})

        agents = [s["agent"] for s in result["plan"]]
        assert "memory" not in agents

    async def test_preference_plus_recommendation_appends_learning(self) -> None:
        """'I love spicy food, what do you recommend?' → recommendation flow + learning."""
        planner = PlannerAgent(mode="keyword")
        state = _make_state("I love spicy food, what do you recommend?")
        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        assert "recommendation" in agents
        assert "learning" in agents
        # learning should be last
        assert agents[-1] == "learning"

    async def test_preference_plus_order_appends_learning(self) -> None:
        """'I enjoy Italian, order me a pasta' → order flow + learning."""
        planner = PlannerAgent(mode="keyword")
        state = _make_state("I enjoy Italian, order me a pasta")
        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        assert "learning" in agents

    async def test_no_double_learning_for_preference_intent(self) -> None:
        """'I'm allergic to peanuts' classified as declare_preference already has learning."""
        planner = PlannerAgent(mode="keyword")
        state = _make_state("I'm allergic to peanuts")
        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        assert agents.count("learning") == 1


# ---------------------------------------------------------------------------
# LLM mode
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPlannerLLM:
    async def test_simple_order(self) -> None:
        client = _mock_anthropic_response(
            {
                "intent": "order_meal",
                "constraints": {"cuisine": "thai"},
                "compound_flags": {"has_preference": False},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want thai food")

        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "order_meal"
        assert result["constraints"]["cuisine"] == "thai"
        # Plan is composed by the flow router from the intent alone.
        agents = [s["agent"] for s in result["plan"]]
        assert agents == ["memory", "menu", "recommendation"]

    async def test_compound_preference_and_order(self) -> None:
        """'I love tofu. I'll have it today' → confirm_order flow + learning."""
        client = _mock_anthropic_response(
            {
                "intent": "confirm_order",
                "constraints": {"selected_item": "Tofu Stir Fry", "preference": "loves tofu"},
                "compound_flags": {"has_preference": True},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I love tofu. I'll have it today")

        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        assert "execution" in agents
        assert "learning" in agents
        # learning is already in confirm_order's flow, so has_preference must
        # NOT duplicate it.
        assert agents.count("learning") == 1
        assert state.constraints["selected_item"] == "Tofu Stir Fry"

    async def test_preference_only(self) -> None:
        client = _mock_anthropic_response(
            {
                "intent": "declare_preference",
                "constraints": {"preference": "vegetarian"},
                "compound_flags": {"has_preference": True},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I'm vegetarian")

        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "declare_preference"
        agents = [s["agent"] for s in result["plan"]]
        assert agents == ["learning"]

    async def test_preference_plus_recommendation_appends_learning(self) -> None:
        """has_preference=true with a non-preference intent appends learning."""
        client = _mock_anthropic_response(
            {
                "intent": "get_recommendation",
                "constraints": {"preference": "spicy"},
                "compound_flags": {"has_preference": True},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I love spicy food, what do you recommend?")

        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        assert agents == ["memory", "menu", "recommendation", "learning"]

    async def test_limits_plan_to_available_agents(self) -> None:
        """Steps for agents not in the registry are dropped by compose_plan."""
        client = _mock_anthropic_response(
            {
                "intent": "order_meal",
                "constraints": {},
                "compound_flags": {"has_preference": False},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("Order food")

        # Memory is not registered in this environment — flow must still run.
        result = await planner.plan(state, {"menu", "recommendation"})

        agents = [s["agent"] for s in result["plan"]]
        assert "memory" not in agents
        assert agents == ["menu", "recommendation"]

    async def test_falls_back_on_api_error(self) -> None:
        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want to order lunch")

        result = await planner.plan(state, ALL_AGENTS)

        # Falls back to keyword → order_meal
        assert result["intent"] == "order_meal"
        assert len(result["plan"]) > 0

    async def test_falls_back_when_composed_plan_is_empty(self) -> None:
        """Intents whose flow is empty (e.g. check_order_status today) fall back.

        Prevents the orchestrator from receiving a no-op plan when the LLM
        classifies into an intent that has no registered handler yet.
        """
        client = _mock_anthropic_response(
            {
                "intent": "check_order_status",
                "constraints": {},
                "compound_flags": {"has_preference": False},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want to order lunch")

        result = await planner.plan(state, ALL_AGENTS)

        # Keyword fallback reclassifies and builds a non-empty plan.
        assert result["intent"] == "order_meal"
        assert len(result["plan"]) > 0

    async def test_out_of_scope_returns_empty_plan(self) -> None:
        client = _mock_anthropic_response(
            {
                "intent": "out_of_scope",
                "constraints": {},
                "compound_flags": {"has_preference": False},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("What's the weather?")

        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "out_of_scope"
        assert result["plan"] == []

    async def test_falls_back_on_invalid_json(self) -> None:
        text_block = MagicMock()
        text_block.text = "not json"
        text_block.type = "text"
        response = MagicMock()
        response.content = [text_block]
        client = AsyncMock()
        client.messages.create = AsyncMock(return_value=response)
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("Order dinner")

        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "order_meal"
        assert len(result["plan"]) > 0

    async def test_llm_without_client_uses_keyword(self) -> None:
        planner = PlannerAgent(mode="llm", anthropic_client=None)
        state = _make_state("I want to order lunch")

        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "order_meal"


# ---------------------------------------------------------------------------
# Orchestrator integration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunPlannedWorkflow:
    async def test_executes_plan_steps(self) -> None:
        from plateful.core.orchestrator import run_planned_workflow

        call_order: list[str] = []

        class RecordingAgent:
            def __init__(self, name: str) -> None:
                self.name = name

            async def run(self, state: WorkflowState) -> WorkflowState:
                call_order.append(self.name)
                return state

        registry: dict[str, Any] = {
            "memory": RecordingAgent("memory"),
            "menu": RecordingAgent("menu"),
            "recommendation": RecordingAgent("recommendation"),
            "learning": RecordingAgent("learning"),
        }

        client = _mock_anthropic_response(
            {
                "intent": "get_recommendation",
                "constraints": {},
                "compound_flags": {"has_preference": False},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("Recommend something")

        await run_planned_workflow(state, registry, planner)

        assert call_order == ["memory", "menu", "recommendation"]

    async def test_compound_intent_runs_all_steps(self) -> None:
        from plateful.core.orchestrator import run_planned_workflow

        call_order: list[str] = []

        class RecordingAgent:
            def __init__(self, name: str) -> None:
                self.name = name

            async def run(self, state: WorkflowState) -> WorkflowState:
                call_order.append(self.name)
                return state

        registry: dict[str, Any] = {
            "memory": RecordingAgent("memory"),
            "menu": RecordingAgent("menu"),
            "execution": RecordingAgent("execution"),
            "learning": RecordingAgent("learning"),
        }

        client = _mock_anthropic_response(
            {
                "intent": "confirm_order",
                "constraints": {"selected_item": "Tofu Stir Fry"},
                "compound_flags": {"has_preference": True},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I love tofu. I'll have it today")

        with patch("plateful.core.observability.get_langfuse", return_value=None):
            await run_planned_workflow(state, registry, planner)

        assert call_order == ["memory", "menu", "execution", "learning"]
