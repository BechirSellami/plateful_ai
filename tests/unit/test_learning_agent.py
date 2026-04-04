from unittest.mock import MagicMock

import pytest

from plateful.agents.learning import LearningAgent
from plateful.core.workflow import WorkflowState


def _make_client() -> MagicMock:
    """Create a mock Mem0 client with add() returning a result dict."""
    client = MagicMock()
    client.add = MagicMock(return_value={"results": [{"id": "mem_1"}]})
    return client


@pytest.mark.unit
class TestLearningAgent:
    async def test_learns_from_submitted_order(self) -> None:
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            order={
                "order_id": "ord_abc",
                "status": "submitted",
                "items": [{"name": "Chicken Bowl", "price_usd": 18.50}],
            },
        )

        result = await agent.run(state)

        assert result.last_result["status"] == "learned"
        assert result.last_result["events_processed"] == 1
        assert "Chicken Bowl" in result.last_result["summary"]

    async def test_skips_when_no_order(self) -> None:
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(user_id="emp_123", session_id="s")

        result = await agent.run(state)

        assert result.last_result["status"] == "skipped"
        client.add.assert_not_called()

    async def test_skips_pending_approval_order(self) -> None:
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            order={
                "order_id": "ord_abc",
                "status": "pending_approval",
                "items": [{"name": "Expensive Meal", "price_usd": 45.00}],
            },
        )

        result = await agent.run(state)

        assert result.last_result["status"] == "skipped"

    async def test_tracks_accepted_suggestions(self) -> None:
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            recommendations=[
                {"name": "Chicken Bowl", "price_usd": 18.50},
                {"name": "Veggie Wrap", "price_usd": 12.00},
            ],
            order={
                "order_id": "ord_abc",
                "status": "submitted",
                "items": [{"name": "Chicken Bowl", "price_usd": 18.50}],
            },
        )

        result = await agent.run(state)

        assert result.last_result["status"] == "learned"
        # Should have order_placed + suggestion_accepted events
        assert result.last_result["events_processed"] == 2
        assert "accepted suggestion" in result.last_result["summary"]

    async def test_calls_mem0_add(self) -> None:
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            order={
                "order_id": "ord_abc",
                "status": "submitted",
                "items": [{"name": "Bowl", "price_usd": 15.00}],
            },
        )

        await agent.run(state)

        client.add.assert_called_once()
        call_kwargs = client.add.call_args
        assert call_kwargs.kwargs["user_id"] == "emp_123"

    async def test_learns_from_preference_declaration(self) -> None:
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            intent="declare_preference",
            messages=[{"role": "user", "content": "I prefer spicy food"}],
        )

        result = await agent.run(state)

        assert result.last_result["status"] == "learned"
        assert "I prefer spicy food" in result.last_result["summary"]
        client.add.assert_called_once()

    async def test_learns_preference_with_constraints(self) -> None:
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            intent="declare_preference",
            constraints={"dietary": "vegan", "cuisine": "thai"},
            messages=[{"role": "user", "content": "I'm vegan and love thai food"}],
        )

        result = await agent.run(state)

        assert result.last_result["status"] == "learned"
        assert result.last_result["events_processed"] >= 2
        summary = result.last_result["summary"]
        assert "vegan" in summary.lower()
        assert "thai" in summary.lower()

    async def test_skips_non_preference_intent_without_order(self) -> None:
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            intent="get_recommendation",
            messages=[{"role": "user", "content": "What do you suggest?"}],
        )

        result = await agent.run(state)

        assert result.last_result["status"] == "skipped"
        client.add.assert_not_called()

    async def test_learns_embedded_preference_in_recommendation(self) -> None:
        """'I love spicy food, what do you recommend?' should save preference."""
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            intent="get_recommendation",
            messages=[{"role": "user", "content": "I love spicy food, what do you recommend?"}],
        )

        result = await agent.run(state)

        assert result.last_result["status"] == "learned"
        assert "I love spicy food" in result.last_result["summary"]
        client.add.assert_called_once()

    async def test_learns_embedded_preference_in_order(self) -> None:
        """'I enjoy Italian, order me a pasta' should save preference."""
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            intent="order_meal",
            messages=[{"role": "user", "content": "I enjoy Italian, order me a pasta"}],
        )

        result = await agent.run(state)

        assert result.last_result["status"] == "learned"
        assert "I enjoy Italian" in result.last_result["summary"]

    async def test_multiple_items_in_order(self) -> None:
        client = _make_client()
        agent = LearningAgent(client=client)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            order={
                "order_id": "ord_abc",
                "status": "submitted",
                "items": [
                    {"name": "Bowl", "price_usd": 15.00},
                    {"name": "Salad", "price_usd": 10.00},
                ],
            },
        )

        result = await agent.run(state)

        assert result.last_result["events_processed"] == 2
        assert "Bowl" in result.last_result["summary"]
        assert "Salad" in result.last_result["summary"]
