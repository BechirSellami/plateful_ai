from unittest.mock import AsyncMock, MagicMock

import pytest

from plateful.core.orchestrator import (
    CATERING_FLOW,
    evaluate_condition,
    get_steps_from,
    register_safety_check,
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
