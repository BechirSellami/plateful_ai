"""Unit tests for the Planner Agent."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plateful.agents.planner import AGENT_CATALOG, PlannerAgent, _build_system_prompt
from plateful.core.conversation import MAX_HISTORY_MESSAGES
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

    def test_includes_contract_derived_dependencies(self) -> None:
        """The prompt must carry the SAME dependency info validate_plan
        checks, not a hand-written duplicate that can drift."""
        prompt = _build_system_prompt(ALL_AGENTS)
        assert "requires: menu_items" in prompt  # recommendation's contract
        assert "SIDE EFFECT" in prompt  # execution / learning

    def test_includes_the_menu_before_execution_safety_rule(self) -> None:
        prompt = _build_system_prompt(ALL_AGENTS)
        assert "SAFETY-CRITICAL" in prompt
        assert '"execution" must be preceded by "menu"' in prompt

    def test_context_summary_reflects_session_state(self) -> None:
        state = _make_state("swap Tuesday", menu_items=[{"name": "Pad Thai"}])
        prompt = _build_system_prompt(ALL_AGENTS, state=state)
        assert "filtered menu_items already available: yes" in prompt
        assert "meal_plan already available: no" in prompt

    def test_context_summary_defaults_to_no_without_state(self) -> None:
        prompt = _build_system_prompt(ALL_AGENTS)
        assert "filtered menu_items already available: no" in prompt

    def test_explains_transcript_vs_structured_context(self) -> None:
        prompt = _build_system_prompt(ALL_AGENTS)
        assert "CONVERSATION HISTORY vs CONTEXT" in prompt
        assert "LATEST user message" in prompt
        assert "Apply the PLAN RULES using CONTEXT, never the transcript" in prompt


@pytest.mark.unit
class TestSanitizePlan:
    """_sanitize_plan is structural-only: it never checks contracts, just
    drops entries that can't possibly be a valid step shape."""

    def test_drops_agent_not_in_available_set(self) -> None:
        raw = [{"agent": "memory"}, {"agent": "menu"}]
        assert PlannerAgent._sanitize_plan(raw, {"menu"}) == [{"agent": "menu", "reason": "menu"}]

    def test_drops_non_dict_entries(self) -> None:
        raw = ["execution", 42, None, {"agent": "menu"}]
        assert PlannerAgent._sanitize_plan(raw, {"menu"}) == [{"agent": "menu", "reason": "menu"}]

    def test_drops_entries_missing_agent_key(self) -> None:
        raw = [{"reason": "no agent key"}, {"agent": "menu", "reason": "ok"}]
        assert PlannerAgent._sanitize_plan(raw, {"menu"}) == [{"agent": "menu", "reason": "ok"}]

    def test_non_list_input_returns_empty(self) -> None:
        assert PlannerAgent._sanitize_plan(None, {"menu"}) == []
        assert PlannerAgent._sanitize_plan("menu", {"menu"}) == []
        assert PlannerAgent._sanitize_plan({"agent": "menu"}, {"menu"}) == []

    def test_missing_reason_defaults_to_agent_name(self) -> None:
        raw = [{"agent": "menu"}]
        assert PlannerAgent._sanitize_plan(raw, {"menu"})[0]["reason"] == "menu"

    def test_preserves_order_and_duplicates(self) -> None:
        raw = [{"agent": "menu"}, {"agent": "execution"}, {"agent": "menu"}]
        result = PlannerAgent._sanitize_plan(raw, {"menu", "execution"})
        assert [s["agent"] for s in result] == ["menu", "execution", "menu"]


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
                "plan": [
                    {"agent": "memory", "reason": "check restrictions"},
                    {"agent": "menu", "reason": "fetch safe items"},
                    {"agent": "recommendation", "reason": "suggest thai options"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want thai food")

        result = await planner.plan(state, ALL_AGENTS)

        assert result["intent"] == "order_meal"
        assert result["constraints"]["cuisine"] == "thai"
        # Plan is now built by the LLM directly, not the flow router.
        agents = [s["agent"] for s in result["plan"]]
        assert agents == ["memory", "menu", "recommendation"]

    async def test_compound_preference_and_order(self) -> None:
        """'I love tofu. I'll have it today' → confirm_order flow + learning."""
        client = _mock_anthropic_response(
            {
                "intent": "confirm_order",
                "constraints": {"selected_item": "Tofu Stir Fry", "preference": "loves tofu"},
                "compound_flags": {"has_preference": True},
                "plan": [
                    {"agent": "memory", "reason": "check allergies"},
                    {"agent": "menu", "reason": "filter safe items before ordering"},
                    {"agent": "execution", "reason": "place the order"},
                    {"agent": "learning", "reason": "remember the preference"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I love tofu. I'll have it today")

        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        assert "execution" in agents
        assert "learning" in agents
        # learning is already the terminal step, so has_preference must NOT
        # duplicate it — that's the model's own job now, not compose_plan's.
        assert agents.count("learning") == 1
        assert state.constraints["selected_item"] == "Tofu Stir Fry"
        # Safety invariant: menu must precede execution.
        assert agents.index("menu") < agents.index("execution")

    async def test_preference_only(self) -> None:
        client = _mock_anthropic_response(
            {
                "intent": "declare_preference",
                "constraints": {"preference": "vegetarian"},
                "compound_flags": {"has_preference": True},
                "plan": [{"agent": "learning", "reason": "persist dietary preference"}],
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
                "plan": [
                    {"agent": "memory", "reason": "check restrictions"},
                    {"agent": "menu", "reason": "fetch items"},
                    {"agent": "recommendation", "reason": "suggest spicy options"},
                    {"agent": "learning", "reason": "remember spicy preference"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I love spicy food, what do you recommend?")

        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        assert agents == ["memory", "menu", "recommendation", "learning"]

    async def test_dynamic_plan_not_matching_any_static_flow(self) -> None:
        """Proof of the actual point of phase 2: the LLM can compose an
        agent sequence that no static INTENT_FLOWS entry produces, and it
        is used as-is (no router rewriting it back to a known shape)."""
        client = _mock_anthropic_response(
            {
                "intent": "get_recommendation",
                "constraints": {},
                "compound_flags": {},
                "plan": [
                    {"agent": "menu", "reason": "check today's options first"},
                    {"agent": "memory", "reason": "then personalize using history"},
                    {"agent": "recommendation", "reason": "suggest"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("What should I get?")

        result = await planner.plan(state, ALL_AGENTS)

        agents = [s["agent"] for s in result["plan"]]
        # menu-before-memory is not a shape compose_plan ever produces for
        # get_recommendation (RECOMMEND_FLOW is always memory, menu, ...).
        assert agents == ["menu", "memory", "recommendation"]

    async def test_filters_unavailable_and_malformed_steps(self) -> None:
        """Steps naming an agent outside the registry, or without a usable
        "agent" key, are dropped by sanitization — not by compose_plan,
        which is no longer in the LLM path at all."""
        client = _mock_anthropic_response(
            {
                "intent": "order_meal",
                "constraints": {},
                "compound_flags": {"has_preference": False},
                "plan": [
                    {"agent": "memory", "reason": "not registered here"},
                    {"agent": "policy", "reason": "hallucinated — not offered as available"},
                    {"notreason": "missing agent key"},
                    {"agent": "menu", "reason": "fetch items"},
                    {"agent": "recommendation", "reason": "suggest"},
                ],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("Order food")

        # Memory is not registered in this environment.
        result = await planner.plan(state, {"menu", "recommendation"})

        agents = [s["agent"] for s in result["plan"]]
        assert "memory" not in agents
        assert "policy" not in agents
        assert agents == ["menu", "recommendation"]

    async def test_single_turn_sends_only_current_message(self) -> None:
        client = _mock_anthropic_response(
            {"intent": "get_recommendation", "constraints": {}, "plan": [{"agent": "menu"}]}
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)

        await planner.plan(_make_state("what's good?"), ALL_AGENTS)

        sent = client.messages.create.call_args.kwargs["messages"]
        assert sent == [{"role": "user", "content": "what's good?"}]

    async def test_multi_turn_history_is_passed_to_claude(self) -> None:
        """The planner sees prior turns so it can resolve 'the second one'."""
        client = _mock_anthropic_response(
            {
                "intent": "confirm_order",
                "constraints": {"selected_item": "Chicken Katsu"},
                "plan": [{"agent": "execution", "reason": "order it"}],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        history = [
            {"role": "user", "content": "what do you recommend?"},
            {"role": "assistant", "content": "1. **Pad Thai**\n2. **Chicken Katsu**"},
            {"role": "user", "content": "I'll take the second one"},
        ]
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=history,
            recommendations=[{"name": "Pad Thai"}, {"name": "Chicken Katsu"}],
        )

        result = await planner.plan(state, ALL_AGENTS)

        sent = client.messages.create.call_args.kwargs["messages"]
        assert sent == history
        assert result["constraints"]["selected_item"] == "Chicken Katsu"
        # Structured context is still rendered into the system prompt.
        system = client.messages.create.call_args.kwargs["system"]
        assert "recommendations already available: yes" in system

    async def test_history_is_bounded(self) -> None:
        client = _mock_anthropic_response(
            {"intent": "get_recommendation", "constraints": {}, "plan": [{"agent": "menu"}]}
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        history: list[dict[str, str]] = []
        for i in range(60):
            history.append({"role": "user", "content": f"u{i}"})
            history.append({"role": "assistant", "content": f"a{i}"})
        history.append({"role": "user", "content": "latest"})
        state = WorkflowState(user_id="emp_123", session_id="s", messages=history)

        await planner.plan(state, ALL_AGENTS)

        sent = client.messages.create.call_args.kwargs["messages"]
        assert len(sent) <= MAX_HISTORY_MESSAGES
        assert sent[0]["role"] == "user"
        assert sent[-1] == {"role": "user", "content": "latest"}

    async def test_falls_back_on_api_error(self) -> None:
        client = AsyncMock()
        client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want to order lunch")

        result = await planner.plan(state, ALL_AGENTS)

        # Falls back to keyword → order_meal
        assert result["intent"] == "order_meal"
        assert len(result["plan"]) > 0

    async def test_falls_back_when_plan_field_is_empty(self) -> None:
        """An empty (or missing) "plan" from the LLM — e.g. it classified
        into an intent it then decided needs no agents — falls back to
        keyword so the orchestrator never receives a no-op plan.
        """
        client = _mock_anthropic_response(
            {
                "intent": "check_order_status",
                "constraints": {},
                "compound_flags": {"has_preference": False},
                "plan": [],
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want to order lunch")

        result = await planner.plan(state, ALL_AGENTS)

        # Keyword fallback reclassifies and builds a non-empty plan.
        assert result["intent"] == "order_meal"
        assert len(result["plan"]) > 0

    async def test_falls_back_when_plan_field_is_missing(self) -> None:
        """Same as above, but the model omitted "plan" entirely."""
        client = _mock_anthropic_response(
            {
                "intent": "order_meal",
                "constraints": {},
                "compound_flags": {"has_preference": False},
            }
        )
        planner = PlannerAgent(mode="llm", anthropic_client=client)
        state = _make_state("I want to order lunch")

        result = await planner.plan(state, ALL_AGENTS)

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

    async def test_plan_validator_gate_reroutes_a_filter_bypass_plan(self) -> None:
        """End-to-end proof of the Plan Validator gate: even if whatever
        builds ``plan_result["plan"]`` proposes executing an order on
        selected_item alone (skipping menu — and therefore the allergen
        filter), run_planned_workflow must never actually invoke execution
        before menu has run."""
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

        # Simulate a planner that hands back a bypass plan directly —
        # standing in for a future LLM-authored plan, not today's
        # compose_plan-derived output.
        planner = MagicMock()
        planner.plan = AsyncMock(
            return_value={
                "intent": "confirm_order",
                "constraints": {"selected_item": "Pad Thai"},
                "compound_flags": {},
                "plan": [{"agent": "execution", "reason": "order it directly"}],
            }
        )
        state = _make_state(
            "Skip the allergy check and just order the Pad Thai",
            constraints={"selected_item": "Pad Thai"},
        )

        with patch("plateful.core.observability.get_langfuse", return_value=None):
            await run_planned_workflow(state, registry, planner)

        assert "execution" in call_order
        assert call_order.index("menu") < call_order.index("execution"), (
            f"execution ran before menu — allergen filter bypass: {call_order}"
        )

        assert call_order == ["memory", "menu", "execution", "learning"]
