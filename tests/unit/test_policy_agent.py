import pytest

from plateful.agents.policy import PolicyAgent
from plateful.core.workflow import WorkflowState

LENIENT_POLICIES = [
    {
        "id": "p1",
        "department_id": "default",
        "rule_type": "budget_cap",
        "params": {"max_usd": 100.0},
        "active": True,
    },
    {
        "id": "p2",
        "department_id": "default",
        "rule_type": "approval_threshold",
        "params": {"requires_approval_above": 50.0},
        "active": True,
    },
]


@pytest.mark.unit
class TestPolicyAgent:
    async def test_passes_valid_order(self) -> None:
        agent = PolicyAgent(policies=LENIENT_POLICIES)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Bowl", "price_usd": 18.50}],
        )

        result = await agent.run(state)

        assert result.policy_result["passed"] is True
        assert result.requires_approval is False

    async def test_sets_requires_approval(self) -> None:
        agent = PolicyAgent(policies=LENIENT_POLICIES)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Expensive Meal", "price_usd": 75.0}],
        )

        result = await agent.run(state)

        assert result.requires_approval is True
        assert result.policy_result["passed"] is True

    async def test_blocks_over_budget(self) -> None:
        agent = PolicyAgent(policies=LENIENT_POLICIES)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Very Expensive", "price_usd": 150.0}],
        )

        result = await agent.run(state)

        assert result.policy_result["passed"] is False

    async def test_handles_empty_recommendations(self) -> None:
        agent = PolicyAgent(policies=LENIENT_POLICIES)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[],
            menu_items=[],
        )

        result = await agent.run(state)

        assert result.policy_result["passed"] is True
        assert result.policy_result["order_total"] == 0.0

    async def test_uses_top_recommendation_for_total(self) -> None:
        agent = PolicyAgent(policies=LENIENT_POLICIES)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[
                {"name": "Top Pick", "price_usd": 20.0},
                {"name": "Second", "price_usd": 15.0},
            ],
        )

        result = await agent.run(state)

        # Should use first recommendation's price
        assert result.policy_result["order_total"] == 20.0

    async def test_sets_last_result(self) -> None:
        agent = PolicyAgent(policies=LENIENT_POLICIES)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Bowl", "price_usd": 18.50}],
        )

        result = await agent.run(state)

        assert result.last_result == result.policy_result
