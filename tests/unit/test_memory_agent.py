from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plateful.agents.memory import MemoryAgent
from plateful.core.workflow import WorkflowState


@pytest.mark.unit
class TestMemoryAgent:
    def _make_agent(self) -> MemoryAgent:
        return MemoryAgent(client=MagicMock())

    async def test_enriches_state_with_user_profile(self) -> None:
        agent = self._make_agent()
        memories = [
            {"memory": "Prefers spicy Thai food"},
            {"memory": "Allergic to peanuts"},
            {"memory": "Usually orders under $20"},
        ]

        with patch("plateful.agents.memory.search_memories", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = memories
            state = WorkflowState(user_id="emp_123", session_id="sess_abc")

            result = await agent.run(state)

        assert result.user_profile["preferences"] == ["Prefers spicy Thai food"]
        assert result.user_profile["allergies"] == ["Allergic to peanuts"]
        assert result.user_profile["budget_preference"] == "Usually orders under $20"
        assert result.user_profile["raw_memories"] == memories

    async def test_handles_empty_memories(self) -> None:
        agent = self._make_agent()

        with patch("plateful.agents.memory.search_memories", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            state = WorkflowState(user_id="emp_123", session_id="sess_abc")

            result = await agent.run(state)

        assert result.user_profile["preferences"] == []
        assert result.user_profile["allergies"] == []

    async def test_categorizes_dietary_restrictions(self) -> None:
        agent = self._make_agent()
        memories = [
            {"memory": "Is vegetarian"},
            {"memory": "Avoids shellfish"},
            {"memory": "Loves Italian cuisine"},
        ]

        with patch("plateful.agents.memory.search_memories", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = memories
            state = WorkflowState(user_id="emp_123", session_id="sess_abc")

            result = await agent.run(state)

        assert result.user_profile["dietary_restrictions"] == ["Is vegetarian"]
        assert result.user_profile["disliked_items"] == ["Avoids shellfish"]
        assert result.user_profile["preferences"] == ["Loves Italian cuisine"]

    async def test_builds_context_query_with_intent(self) -> None:
        agent = self._make_agent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="sess_abc",
            intent="order_lunch",
            constraints={"budget": 25, "meal_type": "lunch"},
        )

        query = agent._build_context_query(state)
        assert "order_lunch" in query
        assert "$25" in query
        assert "lunch" in query

    async def test_builds_fallback_query_without_context(self) -> None:
        agent = self._make_agent()
        state = WorkflowState(user_id="emp_123", session_id="sess_abc")

        query = agent._build_context_query(state)
        assert "food preferences" in query

    async def test_sets_last_result(self) -> None:
        agent = self._make_agent()

        with patch("plateful.agents.memory.search_memories", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            state = WorkflowState(user_id="emp_123", session_id="sess_abc")
            result = await agent.run(state)

        assert result.last_result == result.user_profile


@pytest.mark.unit
class TestMemoryAgentContextQuery:
    def _make_agent(self) -> MemoryAgent:
        return MemoryAgent(client=MagicMock())

    def test_dietary_constraint(self) -> None:
        agent = self._make_agent()
        state = WorkflowState(
            user_id="emp_123",
            session_id="sess_abc",
            constraints={"dietary": "vegan"},
        )
        query = agent._build_context_query(state)
        assert "vegan" in query

    def test_empty_constraints(self) -> None:
        agent = self._make_agent()
        state = WorkflowState(user_id="emp_123", session_id="sess_abc", constraints={})
        query = agent._build_context_query(state)
        assert "food preferences" in query
