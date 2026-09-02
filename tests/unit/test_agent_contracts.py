"""Unit tests for declarative agent contracts and the plan validator.

These tests cover two layers:

1. ``validate_plan`` — unit tests against hand-crafted plans that exercise
   each validation rule (missing inputs, disjunctive groups, post_action
   ordering, unknown agents).
2. Cross-validation of ``flow_router.INTENT_FLOWS`` — confirms that every
   static intent→flow mapping shipped today is consistent with the
   declared contracts under realistic initial-output assumptions. This is
   the "find N inconsistencies in existing flows" check that motivated
   PR 1.
"""

from __future__ import annotations

import pytest

from plateful.core.agent_contracts import (
    AGENT_CONTRACTS,
    AgentContract,
    ValidationIssue,
    state_to_initial_outputs,
    validate_plan,
)
from plateful.core.flow_router import INTENT_FLOWS, get_flow_for_intent
from plateful.core.workflow import WorkflowState

# ---------------------------------------------------------------------------
# validate_plan — unit behavior
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidatePlanHappyPath:
    def test_empty_plan_is_valid(self) -> None:
        result = validate_plan([])
        assert result.is_valid
        assert result.issues == []

    def test_recommendation_flow_with_memory_and_menu_is_valid(self) -> None:
        steps = [
            {"agent": "memory", "name": "enrich"},
            {"agent": "menu", "name": "retrieve"},
            {"agent": "recommendation", "name": "recommend"},
        ]
        result = validate_plan(steps)
        assert result.is_valid, result.issues
        assert "recommendations" in result.produced_outputs
        assert "menu_items" in result.produced_outputs

    def test_preference_only_flow_is_valid(self) -> None:
        steps = [{"agent": "learning", "name": "learn"}]
        result = validate_plan(steps, initial_outputs={"user_message", "preference"})
        assert result.is_valid, result.issues

    def test_mealplan_flow_is_valid(self) -> None:
        steps = [
            {"agent": "memory", "name": "enrich"},
            {"agent": "menu", "name": "retrieve"},
            {"agent": "mealplan", "name": "mealplan"},
        ]
        result = validate_plan(steps)
        assert result.is_valid, result.issues
        assert "meal_plan" in result.produced_outputs

    def test_confirm_order_with_selected_item_and_menu_items_is_valid(self) -> None:
        """Realistic confirm_order: menu ran (this turn or a prior one), so
        the item named by selected_item has actually passed the allergen
        filter."""
        steps = [
            {"agent": "execution", "name": "execute"},
            {"agent": "learning", "name": "learn"},
        ]
        result = validate_plan(
            steps,
            initial_outputs={
                "user_message",
                "intent",
                "constraints",
                "selected_item",
                "menu_items",
            },
        )
        assert result.is_valid, result.issues

    def test_submit_mealplan_with_existing_plan_is_valid(self) -> None:
        steps = [
            {"agent": "execution", "name": "execute"},
            {"agent": "learning", "name": "learn"},
        ]
        result = validate_plan(
            steps,
            initial_outputs={"user_message", "intent", "constraints", "meal_plan"},
        )
        assert result.is_valid, result.issues


@pytest.mark.unit
class TestValidatePlanRequiredInput:
    def test_recommendation_without_menu_is_error(self) -> None:
        steps = [{"agent": "recommendation", "name": "recommend"}]
        result = validate_plan(steps)
        assert not result.is_valid
        codes = [i.code for i in result.errors]
        assert "missing_required_input" in codes
        err = next(i for i in result.errors if i.code == "missing_required_input")
        assert err.agent == "recommendation"
        assert "menu_items" in err.message

    def test_mealplan_without_menu_is_error(self) -> None:
        steps = [{"agent": "mealplan", "name": "mealplan"}]
        result = validate_plan(steps)
        assert not result.is_valid
        assert any(i.code == "missing_required_input" for i in result.errors)


@pytest.mark.unit
class TestValidatePlanRequiredAny:
    def test_execution_with_no_inputs_is_error(self) -> None:
        steps = [{"agent": "execution", "name": "execute"}]
        result = validate_plan(steps, initial_outputs={"user_message"})
        assert not result.is_valid
        assert any(i.code == "missing_required_any" for i in result.errors)

    def test_execution_satisfied_by_recommendations(self) -> None:
        steps = [
            {"agent": "memory", "name": "enrich"},
            {"agent": "menu", "name": "retrieve"},
            {"agent": "recommendation", "name": "recommend"},
            {"agent": "execution", "name": "execute"},
        ]
        result = validate_plan(steps)
        assert result.is_valid, result.issues

    def test_execution_satisfied_by_menu_items(self) -> None:
        steps = [
            {"agent": "menu", "name": "retrieve"},
            {"agent": "execution", "name": "execute"},
        ]
        result = validate_plan(steps)
        assert result.is_valid, result.issues

    def test_execution_with_only_selected_item_is_error(self) -> None:
        """Safety invariant: selected_item alone must never satisfy
        execution's inputs — it bypasses the allergen filter. This is the
        exact plan shape a dynamic planner could produce for "I'll take the
        Pad Thai" if it skips the menu step. See
        tests/evals/plan_safety_redteam.py for the adversarial suite."""
        steps = [{"agent": "execution", "name": "execute"}]
        result = validate_plan(
            steps,
            initial_outputs={"user_message", "intent", "constraints", "selected_item"},
        )
        assert not result.is_valid
        assert any(i.code == "missing_required_any" for i in result.errors)


@pytest.mark.unit
class TestValidatePlanPostActionOrdering:
    def test_learning_last_is_valid(self) -> None:
        steps = [
            {"agent": "menu", "name": "retrieve"},
            {"agent": "recommendation", "name": "recommend"},
            {"agent": "learning", "name": "learn"},
        ]
        result = validate_plan(steps)
        assert result.is_valid, result.issues
        assert not result.warnings

    def test_learning_before_recommendation_is_warning(self) -> None:
        steps = [
            {"agent": "learning", "name": "learn"},
            {"agent": "menu", "name": "retrieve"},
            {"agent": "recommendation", "name": "recommend"},
        ]
        result = validate_plan(steps)
        # Still technically valid (no required-input errors given how the
        # inputs work out) but should surface a post-action warning.
        codes = [i.code for i in result.warnings]
        assert "post_action_out_of_order" in codes
        # Two non-post-action agents follow learning → two warnings.
        warnings = [i for i in result.warnings if i.code == "post_action_out_of_order"]
        assert len(warnings) == 2


@pytest.mark.unit
class TestValidatePlanUnknownAgent:
    def test_unknown_agent_is_warning_not_error(self) -> None:
        steps = [{"agent": "mystery", "name": "mystery"}]
        result = validate_plan(steps)
        # Warning only — the orchestrator already no-ops unknown agents.
        assert result.is_valid
        assert any(i.code == "unknown_agent" for i in result.warnings)

    def test_unknown_agent_does_not_satisfy_downstream_requirements(self) -> None:
        steps = [
            {"agent": "mystery", "name": "mystery"},
            {"agent": "recommendation", "name": "recommend"},
        ]
        result = validate_plan(steps)
        assert not result.is_valid
        assert any(i.code == "missing_required_input" for i in result.errors)


# ---------------------------------------------------------------------------
# state_to_initial_outputs
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStateToInitialOutputs:
    def test_empty_state_returns_user_message_only(self) -> None:
        state = WorkflowState()
        outputs = state_to_initial_outputs(state)
        assert outputs == {"user_message"}

    def test_extracted_constraints_are_included(self) -> None:
        state = WorkflowState(
            intent="confirm_order",
            constraints={"selected_item": "Pad Thai", "preference": "spicy"},
        )
        outputs = state_to_initial_outputs(state)
        assert {"user_message", "intent", "constraints", "selected_item", "preference"} <= outputs

    def test_populated_menu_and_recommendations_are_included(self) -> None:
        state = WorkflowState(
            menu_items=[{"name": "Pad Thai"}],
            recommendations=[{"name": "Pad Thai", "score": 0.9}],
        )
        outputs = state_to_initial_outputs(state)
        assert "menu_items" in outputs
        assert "recommendations" in outputs

    def test_existing_meal_plan_and_order_are_included(self) -> None:
        state = WorkflowState(
            meal_plan={"Monday": {"name": "Pad Thai"}},
            order={"id": "ord-1", "status": "submitted"},
        )
        outputs = state_to_initial_outputs(state)
        assert {"meal_plan", "order"} <= outputs


# ---------------------------------------------------------------------------
# Cross-validation: every static INTENT_FLOWS entry must validate cleanly
# under realistic initial-output assumptions for that intent.
# ---------------------------------------------------------------------------


# Per-intent initial outputs representing what the planner / understand
# step realistically populates by the time the rest of the flow runs.
INTENT_INITIAL_OUTPUTS: dict[str, set[str]] = {
    "declare_preference": {"user_message", "intent", "constraints", "preference"},
    "order_meal": {"user_message", "intent", "constraints"},
    "confirm_order": {"user_message", "intent", "constraints", "selected_item"},
    "get_recommendation": {"user_message", "intent", "constraints"},
    "create_mealplan": {"user_message", "intent", "constraints"},
    "submit_mealplan": {"user_message", "intent", "constraints", "meal_plan"},
    "check_order_status": {"user_message", "intent", "constraints"},
    "ask_question": {"user_message", "intent", "constraints"},
    "out_of_scope": {"user_message", "intent", "constraints"},
}


@pytest.mark.unit
@pytest.mark.parametrize("intent", sorted(INTENT_FLOWS.keys()))
def test_intent_flow_matches_contracts(intent: str) -> None:
    available = {
        "orchestrator",
        "memory",
        "menu",
        "recommendation",
        "mealplan",
        "execution",
        "learning",
    }
    flow = get_flow_for_intent(intent, available)
    # flow_router prepends the understand step, which is executed in
    # Phase 1 before run_workflow; strip it for validation.
    steps = [s for s in flow["steps"] if s["name"] != "understand"]

    initial = INTENT_INITIAL_OUTPUTS[intent]
    result = validate_plan(steps, initial_outputs=initial)

    assert result.is_valid, f"Intent {intent!r} flow failed validation:\n" + "\n".join(
        f"  - {i.code}: {i.message}" for i in result.errors
    )


# ---------------------------------------------------------------------------
# Custom contracts — regression guard for the contract registry shape
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestContractRegistry:
    def test_all_contracts_have_matching_name(self) -> None:
        for key, contract in AGENT_CONTRACTS.items():
            assert key == contract.name, (
                f"Registry key {key!r} does not match contract name {contract.name!r}"
            )

    def test_learning_is_post_action(self) -> None:
        assert AGENT_CONTRACTS["learning"].post_action is True

    def test_execution_is_side_effect(self) -> None:
        assert AGENT_CONTRACTS["execution"].side_effect is True

    def test_validator_accepts_custom_contract_override(self) -> None:
        """Callers can swap the registry (e.g. for a minimal test world)."""
        custom = {
            "a": AgentContract(name="a", produces=("foo",)),
            "b": AgentContract(name="b", requires=("foo",), produces=("bar",)),
        }
        steps = [{"agent": "a", "name": "a"}, {"agent": "b", "name": "b"}]
        result = validate_plan(steps, contracts=custom)
        assert result.is_valid
        assert {"foo", "bar"} <= result.produced_outputs

    def test_validation_issue_is_hashable(self) -> None:
        # Frozen dataclass — sanity check.
        issue = ValidationIssue(
            severity="error",
            code="x",
            agent="a",
            step="s",
            message="m",
        )
        assert issue.to_dict()["code"] == "x"
