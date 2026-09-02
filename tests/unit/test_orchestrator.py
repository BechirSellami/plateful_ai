from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import pytest

from plateful.core.flow_router import compose_plan
from plateful.core.orchestrator import (
    CATERING_FLOW,
    evaluate_condition,
    get_steps_from,
    register_safety_check,
    resolve_validated_plan,
    run_adaptive_workflow,
    run_workflow,
)
from plateful.core.workflow import WorkflowState


@pytest.mark.unit
class TestEvaluateCondition:
    def test_true_condition(self) -> None:
        state = WorkflowState(user_id="emp_123", session_id="s")
        state.requires_approval = True
        assert evaluate_condition("state.requires_approval == True", state) is True

    def test_false_condition(self) -> None:
        state = WorkflowState(user_id="emp_123", session_id="s")
        state.requires_approval = False
        assert evaluate_condition("state.requires_approval == True", state) is False

    def test_invalid_condition_returns_false(self) -> None:
        state = WorkflowState(user_id="emp_123", session_id="s")
        assert evaluate_condition("state.nonexistent_attr", state) is False


@pytest.mark.unit
class TestGetStepsFrom:
    def test_returns_steps_after_target(self) -> None:
        remaining = get_steps_from(CATERING_FLOW, start_after="approve")
        names = [s["name"] for s in remaining]
        assert "execute" in names
        assert "learn" in names
        assert "approve" not in names

    def test_returns_empty_for_last_step(self) -> None:
        remaining = get_steps_from(CATERING_FLOW, start_after="learn")
        assert remaining == []

    def test_returns_empty_for_unknown_step(self) -> None:
        remaining = get_steps_from(CATERING_FLOW, start_after="nonexistent")
        assert remaining == []


@pytest.mark.unit
class TestRunWorkflow:
    async def test_executes_all_steps(self) -> None:
        agent1 = AsyncMock()
        agent2 = AsyncMock()

        state = WorkflowState(user_id="emp_123", session_id="s")
        agent1.run.return_value = state
        agent2.run.return_value = state

        flow = {
            "steps": [
                {"name": "step1", "agent": "agent1"},
                {"name": "step2", "agent": "agent2"},
            ]
        }

        result = await run_workflow(flow, state, {"agent1": agent1, "agent2": agent2})

        agent1.run.assert_awaited_once()
        agent2.run.assert_awaited_once()
        assert result == state

    async def test_skips_step_when_condition_not_met(self) -> None:
        agent1 = AsyncMock()
        agent2 = AsyncMock()

        state = WorkflowState(user_id="emp_123", session_id="s")
        state.requires_approval = False
        agent1.run.return_value = state

        flow = {
            "steps": [
                {"name": "step1", "agent": "agent1"},
                {
                    "name": "step2",
                    "agent": "agent2",
                    "condition": "state.requires_approval == True",
                },
            ]
        }

        await run_workflow(flow, state, {"agent1": agent1, "agent2": agent2})

        agent1.run.assert_awaited_once()
        agent2.run.assert_not_awaited()

    async def test_runs_step_when_condition_met(self) -> None:
        agent1 = AsyncMock()
        agent2 = AsyncMock()

        state = WorkflowState(user_id="emp_123", session_id="s")
        state.requires_approval = True
        agent1.run.return_value = state
        agent2.run.return_value = state

        flow = {
            "steps": [
                {"name": "step1", "agent": "agent1"},
                {
                    "name": "step2",
                    "agent": "agent2",
                    "condition": "state.requires_approval == True",
                },
            ]
        }

        await run_workflow(flow, state, {"agent1": agent1, "agent2": agent2})

        agent2.run.assert_awaited_once()

    async def test_skips_missing_agent(self) -> None:
        state = WorkflowState(user_id="emp_123", session_id="s")
        flow = {"steps": [{"name": "step1", "agent": "missing"}]}

        result = await run_workflow(flow, state, {})
        assert result == state

    async def test_calls_audit_function(self) -> None:
        agent = AsyncMock()
        state = WorkflowState(user_id="emp_123", session_id="s")
        agent.run.return_value = state
        audit_fn = MagicMock()

        flow = {"steps": [{"name": "step1", "agent": "agent1"}]}

        await run_workflow(flow, state, {"agent1": agent}, audit_fn=audit_fn)

        audit_fn.assert_called_once()

    async def test_runs_post_check(self) -> None:
        agent = AsyncMock()
        state = WorkflowState(user_id="emp_123", session_id="s")
        agent.run.return_value = state

        check_fn = MagicMock()
        register_safety_check("test_check", check_fn)

        flow = {"steps": [{"name": "step1", "agent": "agent1", "post_check": "test_check"}]}

        await run_workflow(flow, state, {"agent1": agent})

        check_fn.assert_called_once_with(state)


@pytest.mark.unit
class TestResolveValidatedPlan:
    """The Plan Validator gate: a contract-violating plan must never reach
    the executor unmodified. See AGENT_CONTRACTS["execution"] and
    tests/evals/plan_safety_redteam.py for the invariant being enforced."""

    AVAILABLE: ClassVar[set[str]] = {"memory", "menu", "recommendation", "execution", "learning"}

    def test_valid_plan_passes_through_unchanged(self) -> None:
        plan_result = {
            "intent": "get_recommendation",
            "constraints": {},
            "compound_flags": {},
            "plan": [
                {"agent": "memory", "reason": "enrich"},
                {"agent": "menu", "reason": "retrieve"},
                {"agent": "recommendation", "reason": "recommend"},
            ],
        }
        state = WorkflowState(user_id="emp_123", session_id="s")

        steps, validation, used_fallback = resolve_validated_plan(
            plan_result, state, self.AVAILABLE
        )

        assert used_fallback is False
        assert validation.is_valid
        assert [s["agent"] for s in steps] == ["memory", "menu", "recommendation"]

    def test_filter_bypass_plan_is_rejected_and_replaced(self) -> None:
        """A plan that would let execution place an order on selected_item
        alone (no menu step, no menu_items ever produced) must be rejected
        and replaced by the deterministic, contract-valid fallback."""
        plan_result = {
            "intent": "confirm_order",
            "constraints": {"selected_item": "Pad Thai"},
            "compound_flags": {},
            "plan": [{"agent": "execution", "reason": "order it directly"}],
        }
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"selected_item": "Pad Thai"},
        )

        steps, validation, used_fallback = resolve_validated_plan(
            plan_result, state, self.AVAILABLE
        )

        assert used_fallback is True
        assert not validation.is_valid
        assert any(i.code == "missing_required_any" for i in validation.errors)

        expected = compose_plan("confirm_order", self.AVAILABLE, compound_flags={})
        assert [s["agent"] for s in steps] == [s["agent"] for s in expected]
        # The fallback must include menu ahead of execution — that's the
        # whole point of falling back.
        assert steps.index(next(s for s in steps if s["agent"] == "menu")) < steps.index(
            next(s for s in steps if s["agent"] == "execution")
        )

    def test_fallback_plan_itself_validates_cleanly(self) -> None:
        """Sanity check that the replacement plan doesn't just avoid the
        original error while introducing a new one."""
        plan_result = {
            "intent": "confirm_order",
            "constraints": {"selected_item": "Pad Thai"},
            "compound_flags": {},
            "plan": [{"agent": "execution", "reason": "order it directly"}],
        }
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"selected_item": "Pad Thai"},
        )

        steps, _validation, used_fallback = resolve_validated_plan(
            plan_result, state, self.AVAILABLE
        )
        assert used_fallback is True

        from plateful.core.agent_contracts import state_to_initial_outputs, validate_plan

        replay = validate_plan(steps, initial_outputs=state_to_initial_outputs(state))
        assert replay.is_valid, replay.issues


@pytest.mark.unit
class TestRunAdaptiveWorkflow:
    async def test_preference_only_runs_understand_and_learn(self) -> None:
        """declare_preference should skip menu and recommend."""
        intent_agent = AsyncMock()
        learning_agent = AsyncMock()
        menu_agent = AsyncMock()
        recommend_agent = AsyncMock()

        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"role": "user", "content": "I like spicy food"}],
        )

        # Intent agent sets intent to declare_preference
        async def classify(s: WorkflowState) -> WorkflowState:
            s.intent = "declare_preference"
            return s

        intent_agent.run = AsyncMock(side_effect=classify)
        learning_agent.run = AsyncMock(return_value=state)

        registry = {
            "orchestrator": intent_agent,
            "menu": menu_agent,
            "recommendation": recommend_agent,
            "learning": learning_agent,
        }

        result = await run_adaptive_workflow(state, registry)

        intent_agent.run.assert_awaited_once()
        learning_agent.run.assert_awaited_once()
        menu_agent.run.assert_not_awaited()
        recommend_agent.run.assert_not_awaited()
        assert result.intent == "declare_preference"

    async def test_recommendation_runs_full_pipeline(self) -> None:
        """get_recommendation should run enrich, retrieve, recommend."""
        intent_agent = AsyncMock()
        memory_agent = AsyncMock()
        menu_agent = AsyncMock()
        recommend_agent = AsyncMock()

        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[{"role": "user", "content": "What should I eat?"}],
        )

        async def classify(s: WorkflowState) -> WorkflowState:
            s.intent = "get_recommendation"
            return s

        intent_agent.run = AsyncMock(side_effect=classify)
        memory_agent.run = AsyncMock(return_value=state)
        menu_agent.run = AsyncMock(return_value=state)
        recommend_agent.run = AsyncMock(return_value=state)

        registry = {
            "orchestrator": intent_agent,
            "memory": memory_agent,
            "menu": menu_agent,
            "recommendation": recommend_agent,
        }

        await run_adaptive_workflow(state, registry)

        intent_agent.run.assert_awaited_once()
        memory_agent.run.assert_awaited_once()
        menu_agent.run.assert_awaited_once()
        recommend_agent.run.assert_awaited_once()

    async def test_adapts_to_missing_agents(self) -> None:
        """If memory agent is not registered, enrich step is skipped."""
        intent_agent = AsyncMock()
        menu_agent = AsyncMock()
        recommend_agent = AsyncMock()

        state = WorkflowState(user_id="emp_123", session_id="s")

        async def classify(s: WorkflowState) -> WorkflowState:
            s.intent = "get_recommendation"
            return s

        intent_agent.run = AsyncMock(side_effect=classify)
        menu_agent.run = AsyncMock(return_value=state)
        recommend_agent.run = AsyncMock(return_value=state)

        registry = {
            "orchestrator": intent_agent,
            "menu": menu_agent,
            "recommendation": recommend_agent,
        }

        await run_adaptive_workflow(state, registry)

        intent_agent.run.assert_awaited_once()
        menu_agent.run.assert_awaited_once()
        recommend_agent.run.assert_awaited_once()
