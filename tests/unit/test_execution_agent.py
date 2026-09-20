import pytest

from plateful.agents.execution import ExecutionAgent
from plateful.core.workflow import WorkflowState


@pytest.mark.unit
class TestExecutionAgent:
    async def test_submits_order_from_recommendation(self) -> None:
        agent = ExecutionAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Grilled Chicken Bowl", "price_usd": 18.50}],
            policy_result={"passed": True},
        )

        result = await agent.run(state)

        assert result.order is not None
        assert result.order["status"] == "submitted"
        assert result.order["total_usd"] == 18.50
        assert result.order["user_id"] == "emp_123"

    async def test_order_pending_when_approval_required(self) -> None:
        agent = ExecutionAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Expensive Meal", "price_usd": 45.00}],
            policy_result={"passed": True},
            requires_approval=True,
        )

        result = await agent.run(state)

        assert result.order is not None
        assert result.order["status"] == "pending_approval"

    async def test_blocks_when_policy_failed(self) -> None:
        agent = ExecutionAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Very Expensive", "price_usd": 200.00}],
            policy_result={
                "passed": False,
                "violations": [{"message": "Exceeds budget cap"}],
            },
        )

        result = await agent.run(state)

        assert result.order is None
        assert result.last_result["status"] == "blocked"
        assert "Policy violations" in result.last_result["reason"]

    async def test_sends_confirmation_notification(self) -> None:
        agent = ExecutionAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Bowl", "price_usd": 15.00}],
            policy_result={"passed": True},
        )

        result = await agent.run(state)

        assert "notification" in result.last_result
        assert result.last_result["notification"]["user_id"] == "emp_123"

    async def test_sends_approval_pending_notification(self) -> None:
        agent = ExecutionAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Bowl", "price_usd": 35.00}],
            policy_result={"passed": True},
            requires_approval=True,
        )

        result = await agent.run(state)

        notification_msg = result.last_result["notification"]["message"]
        assert "pending" in notification_msg.lower()

    async def test_resolves_selected_item_from_constraints(self) -> None:
        agent = ExecutionAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"selected_item": "Chicken Bowl"},
            menu_items=[
                {"name": "Grilled Chicken Bowl", "price_usd": 18.50},
                {"name": "Tofu Stir Fry", "price_usd": 14.00},
                {"name": "Salmon Poke Bowl", "price_usd": 19.00},
            ],
            policy_result={"passed": True},
        )

        result = await agent.run(state)

        assert result.order is not None
        assert result.order["items"][0]["name"] == "Grilled Chicken Bowl"
        assert result.order["total_usd"] == 18.50

    async def test_resolves_selected_item_fuzzy_match(self) -> None:
        agent = ExecutionAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"selected_item": "salmon"},
            menu_items=[
                {"name": "Grilled Chicken Bowl", "price_usd": 18.50},
                {"name": "Salmon Poke Bowl", "price_usd": 19.00},
            ],
            policy_result={"passed": True},
        )

        result = await agent.run(state)

        assert result.order is not None
        assert result.order["items"][0]["name"] == "Salmon Poke Bowl"

    async def test_falls_back_to_recommendation_when_no_match(self) -> None:
        agent = ExecutionAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"selected_item": "nonexistent item"},
            menu_items=[
                {"name": "Grilled Chicken Bowl", "price_usd": 18.50},
            ],
            recommendations=[{"name": "Tofu Stir Fry", "price_usd": 14.00}],
            policy_result={"passed": True},
        )

        result = await agent.run(state)

        assert result.order is not None
        assert result.order["items"][0]["name"] == "Tofu Stir Fry"

    async def test_resolves_ordinal_against_recommendations(self) -> None:
        """ "The 2nd one" orders the second card, even with no selected_item."""
        agent = ExecutionAgent()
        recs = [
            {"name": "Grilled Chicken Bowl", "price_usd": 18.50},
            {"name": "Salmon Poke Bowl", "price_usd": 24.00},
            {"name": "Mediterranean Grain Bowl", "price_usd": 16.50},
        ]
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            messages=[
                {"role": "user", "content": "What do you recommend today?"},
                {"role": "assistant", "content": "1. Grilled Chicken Bowl\n2. Salmon..."},
                {"role": "user", "content": "I'll take the 2nd one"},
            ],
            menu_items=list(recs),
            recommendations=recs,
            policy_result={"passed": True},
        )

        result = await agent.run(state)

        assert result.order is not None
        assert result.order["items"][0]["name"] == "Salmon Poke Bowl"
        assert result.order["total_usd"] == 24.00

    async def test_ordinal_wins_when_planner_copies_the_phrase(self) -> None:
        """selected_item="the 2nd one" must not fuzzy-match on "the"."""
        agent = ExecutionAgent()
        recs = [
            {"name": "The Works Pizza", "price_usd": 15.00},
            {"name": "Salmon Poke Bowl", "price_usd": 24.00},
        ]
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"selected_item": "the 2nd one"},
            messages=[{"role": "user", "content": "I'll take the 2nd one"}],
            menu_items=list(recs),
            recommendations=recs,
            policy_result={"passed": True},
        )

        result = await agent.run(state)

        assert result.order is not None
        assert result.order["items"][0]["name"] == "Salmon Poke Bowl"

    async def test_explicit_name_beats_ordinal(self) -> None:
        agent = ExecutionAgent()
        recs = [
            {"name": "Grilled Chicken Bowl", "price_usd": 18.50},
            {"name": "Salmon Poke Bowl", "price_usd": 24.00},
        ]
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            constraints={"selected_item": "Grilled Chicken Bowl"},
            messages=[{"role": "user", "content": "The chicken bowl — the 2nd one is too pricey"}],
            menu_items=list(recs),
            recommendations=recs,
            policy_result={"passed": True},
        )

        result = await agent.run(state)

        assert result.order is not None
        assert result.order["items"][0]["name"] == "Grilled Chicken Bowl"

    async def test_handles_empty_items(self) -> None:
        agent = ExecutionAgent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[],
            menu_items=[],
            policy_result={"passed": True},
        )

        result = await agent.run(state)

        assert result.order is None
        assert result.last_result["status"] == "error"

    async def test_order_has_unique_id(self) -> None:
        agent = ExecutionAgent()
        state1 = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Bowl", "price_usd": 15.00}],
            policy_result={"passed": True},
        )
        state2 = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[{"name": "Bowl", "price_usd": 15.00}],
            policy_result={"passed": True},
        )

        result1 = await agent.run(state1)
        result2 = await agent.run(state2)

        assert result1.order["order_id"] != result2.order["order_id"]


@pytest.mark.unit
class TestExecutionTools:
    async def test_submit_order_returns_order(self) -> None:
        from plateful.tools.execution_tools import submit_order

        order = await submit_order(
            user_id="emp_123",
            items=[{"name": "Bowl", "price_usd": 15}],
            total_usd=15.0,
        )
        assert order["order_id"].startswith("ord_")
        assert order["status"] == "submitted"
        assert order["user_id"] == "emp_123"

    async def test_submit_order_pending_approval(self) -> None:
        from plateful.tools.execution_tools import submit_order

        order = await submit_order(
            user_id="emp_123",
            items=[{"name": "Bowl", "price_usd": 15}],
            total_usd=15.0,
            requires_approval=True,
        )
        assert order["status"] == "pending_approval"

    async def test_send_notification(self) -> None:
        from plateful.tools.execution_tools import send_notification

        notif = await send_notification(user_id="emp_123", message="Order placed!")
        assert notif["notification_id"].startswith("notif_")
        assert notif["user_id"] == "emp_123"
        assert notif["message"] == "Order placed!"
