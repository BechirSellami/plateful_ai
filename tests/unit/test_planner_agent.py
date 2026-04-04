"""Unit tests for the Planner Agent."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

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
                "plan": [
                    {"agent": "memory", "reason": "Load preferences"},
                    {"agent": "menu", "reason": "Get menu"},
                    {"agent": "recommendation", "reason": "Suggest items"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want thai food")

        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "order_meal"
        assert result["constraints"]["cuisine"] == "thai"
        agents = [s["agent"] for s in result["plan"]]
        assert agents == ["memory", "menu", "recommendation"]

    async def test_compound_preference_and_order(self) -> None:
        """'I love tofu. I'll have it today' → learn + execute."""
        client = _mock_anthropic_response(
            {
                "intent": "confirm_order",
                "constraints": {"selected_item": "Tofu Stir Fry", "preference": "loves tofu"},
                "plan": [
                    {"agent": "memory", "reason": "Load preferences for allergen check"},
                    {"agent": "menu", "reason": "Get menu to resolve item"},
                    {"agent": "execution", "reason": "Place order for Tofu Stir Fry"},
                    {"agent": "learning", "reason": "Save tofu preference and order"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I love tofu. I'll have it today")

        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        assert "execution" in agents
        assert "learning" in agents
        assert state.constraints["selected_item"] == "Tofu Stir Fry"

    async def test_preference_only(self) -> None:
        client = _mock_anthropic_response(
            {
                "intent": "declare_preference",
                "constraints": {"preference": "vegetarian"},
                "plan": [
                    {"agent": "learning", "reason": "Save vegetarian preference"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I'm vegetarian")

        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "declare_preference"
        agents = [s["agent"] for s in result["plan"]]
        assert agents == ["learning"]

    async def test_filters_unknown_agents_from_plan(self) -> None:
        client = _mock_anthropic_response(
            {
                "intent": "order_meal",
                "constraints": {},
                "plan": [
                    {"agent": "memory", "reason": "Load"},
                    {"agent": "nonexistent_agent", "reason": "Hallucinated"},
                    {"agent": "menu", "reason": "Get menu"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("Order food")

        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        assert "nonexistent_agent" not in agents
        assert "memory" in agents
        assert "menu" in agents

    async def test_falls_back_on_api_error(self) -> None:
        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want to order lunch")

        result = await planner.plan(state, ALL_AGENTS)

        # Falls back to keyword → order_meal
        assert result["intent"] == "order_meal"
        assert len(result["plan"]) > 0

    async def test_falls_back_on_empty_plan(self) -> None:
        client = _mock_anthropic_response(
            {
                "intent": "order_meal",
                "constraints": {},
                "plan": [],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want to order lunch")

        result = await planner.plan(state, ALL_AGENTS)

        # Empty plan triggers keyword fallback
        assert result["intent"] == "order_meal"
        assert len(result["plan"]) > 0

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
                "plan": [
                    {"agent": "memory", "reason": "Load prefs"},
                    {"agent": "menu", "reason": "Get menu"},
                    {"agent": "recommendation", "reason": "Suggest"},
                ],
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
                "plan": [
                    {"agent": "memory", "reason": "Load prefs"},
                    {"agent": "menu", "reason": "Resolve item"},
                    {"agent": "execution", "reason": "Place order"},
                    {"agent": "learning", "reason": "Save preference + order"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I love tofu. I'll have it today")

        await run_planned_workflow(state, registry, planner)

        assert call_order == ["memory", "menu", "execution", "learning"]
