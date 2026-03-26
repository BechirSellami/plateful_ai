from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plateful.agents.recommendation import RecommendationAgent
from plateful.core.workflow import WorkflowState

SAMPLE_MENU_ITEMS = [
    {
        "id": "1",
        "name": "Grilled Chicken Bowl",
        "description": "Marinated chicken with rice",
        "price_usd": 18.50,
        "category": "healthy",
        "cuisine": "thai",
        "calories": 450,
    },
    {
        "id": "2",
        "name": "Pasta Carbonara",
        "description": "Classic Roman pasta",
        "price_usd": 22.00,
        "category": "comfort",
        "cuisine": "italian",
        "calories": 750,
    },
    {
        "id": "3",
        "name": "Tofu Stir Fry",
        "description": "Crispy tofu with ginger-garlic",
        "price_usd": 14.00,
        "category": "healthy",
        "cuisine": "thai",
        "calories": 350,
    },
]


@pytest.mark.unit
class TestRecommendationAgentDeterministic:
    """Tests for the deterministic (no-LLM) path."""

    async def test_ranks_and_recommends_without_llm(self) -> None:
        agent = RecommendationAgent(anthropic_client=None)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            menu_items=SAMPLE_MENU_ITEMS,
        )

        result = await agent.run(state)

        assert len(result.recommendations) == 3
        assert isinstance(result.last_result, str)
        assert "top picks" in result.last_result.lower()

    async def test_recommendations_have_scores(self) -> None:
        agent = RecommendationAgent(anthropic_client=None)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            menu_items=SAMPLE_MENU_ITEMS,
        )

        result = await agent.run(state)

        for rec in result.recommendations:
            assert "score" in rec

    async def test_respects_user_profile(self) -> None:
        agent = RecommendationAgent(anthropic_client=None)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            menu_items=SAMPLE_MENU_ITEMS,
            user_profile={"favorite_cuisines": ["thai"]},
        )

        result = await agent.run(state)

        # Thai items should be ranked higher
        top_rec = result.recommendations[0]
        assert top_rec["cuisine"] == "thai"

    async def test_handles_empty_menu(self) -> None:
        agent = RecommendationAgent(anthropic_client=None)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            menu_items=[],
        )

        result = await agent.run(state)

        assert result.recommendations == []
        assert "No items" in str(result.last_result)

    async def test_limits_to_3_recommendations(self) -> None:
        many_items = SAMPLE_MENU_ITEMS * 3  # 9 items
        agent = RecommendationAgent(anthropic_client=None)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            menu_items=many_items,
        )

        result = await agent.run(state)

        assert len(result.recommendations) <= 3

    async def test_single_item_menu(self) -> None:
        agent = RecommendationAgent(anthropic_client=None)
        state = WorkflowState(
            user_id="emp_123",
            session_id="s",
            menu_items=[SAMPLE_MENU_ITEMS[0]],
        )

        result = await agent.run(state)

        assert len(result.recommendations) == 1


@pytest.mark.unit
class TestRecommendationAgentWithLLM:
    """Tests for the LLM-powered path (mocked)."""

    async def test_uses_claude_when_client_provided(self) -> None:
        mock_client = AsyncMock()
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_block.text = "I recommend the Grilled Chicken Bowl!"
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_client.messages.create.return_value = mock_response

        agent = RecommendationAgent(anthropic_client=mock_client)

        with patch("plateful.agents.recommendation.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-test"
            state = WorkflowState(
                user_id="emp_123",
                session_id="s",
                menu_items=SAMPLE_MENU_ITEMS,
            )
            result = await agent.run(state)

        assert "Grilled Chicken Bowl" in str(result.last_result)
        mock_client.messages.create.assert_awaited_once()

    async def test_falls_back_on_llm_error(self) -> None:
        mock_client = AsyncMock()
        mock_client.messages.create.side_effect = Exception("API error")

        agent = RecommendationAgent(anthropic_client=mock_client)

        with patch("plateful.agents.recommendation.settings") as mock_settings:
            mock_settings.anthropic_api_key = "sk-test"
            state = WorkflowState(
                user_id="emp_123",
                session_id="s",
                menu_items=SAMPLE_MENU_ITEMS,
            )
            result = await agent.run(state)

        # Should fall back to deterministic
        assert isinstance(result.last_result, str)
        assert "top picks" in result.last_result.lower()

    async def test_skips_llm_without_api_key(self) -> None:
        mock_client = AsyncMock()
        agent = RecommendationAgent(anthropic_client=mock_client)

        with patch("plateful.agents.recommendation.settings") as mock_settings:
            mock_settings.anthropic_api_key = ""
            state = WorkflowState(
                user_id="emp_123",
                session_id="s",
                menu_items=SAMPLE_MENU_ITEMS,
            )
            result = await agent.run(state)

        # Should use deterministic path
        mock_client.messages.create.assert_not_awaited()
        assert "top picks" in str(result.last_result).lower()
