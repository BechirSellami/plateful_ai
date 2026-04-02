from unittest.mock import MagicMock

import pytest

from plateful.core.mem0_client import add_memories, get_all_memories, search_memories


@pytest.mark.unit
class TestSearchMemories:
    async def test_returns_results_from_v2_format(self) -> None:
        client = MagicMock()
        client.search.return_value = {"results": [{"memory": "Likes spicy food"}]}

        result = await search_memories(client, query="food preferences", user_id="emp_123")

        assert len(result) == 1
        assert result[0]["memory"] == "Likes spicy food"
        client.search.assert_called_once_with(
            query="food preferences", filters={"user_id": "emp_123"}, limit=10
        )

    async def test_returns_results_from_legacy_list_format(self) -> None:
        client = MagicMock()
        client.search.return_value = [{"memory": "Likes spicy food"}]

        result = await search_memories(client, query="food preferences", user_id="emp_123")

        assert len(result) == 1
        assert result[0]["memory"] == "Likes spicy food"

    async def test_returns_empty_on_error(self) -> None:
        client = MagicMock()
        client.search.side_effect = Exception("Connection failed")

        result = await search_memories(client, query="test", user_id="emp_123")

        assert result == []

    async def test_custom_limit(self) -> None:
        client = MagicMock()
        client.search.return_value = {"results": []}

        await search_memories(client, query="test", user_id="emp_123", limit=5)

        client.search.assert_called_once_with(query="test", filters={"user_id": "emp_123"}, limit=5)


@pytest.mark.unit
class TestAddMemories:
    async def test_adds_successfully(self) -> None:
        client = MagicMock()
        client.add.return_value = {"status": "ok"}

        result = await add_memories(
            client,
            messages=[{"role": "user", "content": "I prefer spicy food"}],
            user_id="emp_123",
        )

        assert result == {"status": "ok"}

    async def test_returns_empty_on_error(self) -> None:
        client = MagicMock()
        client.add.side_effect = Exception("API error")

        result = await add_memories(
            client,
            messages=[{"role": "user", "content": "test"}],
            user_id="emp_123",
        )

        assert result == {}


@pytest.mark.unit
class TestGetAllMemories:
    async def test_returns_all_memories_from_v2_format(self) -> None:
        client = MagicMock()
        client.get_all.return_value = {"results": [{"memory": "Fact 1"}, {"memory": "Fact 2"}]}

        result = await get_all_memories(client, user_id="emp_123")

        assert len(result) == 2
        client.get_all.assert_called_once_with(filters={"user_id": "emp_123"})

    async def test_returns_all_memories_from_legacy_list_format(self) -> None:
        client = MagicMock()
        client.get_all.return_value = [{"memory": "Fact 1"}]

        result = await get_all_memories(client, user_id="emp_123")

        assert len(result) == 1

    async def test_returns_empty_on_error(self) -> None:
        client = MagicMock()
        client.get_all.side_effect = Exception("Timeout")

        result = await get_all_memories(client, user_id="emp_123")

        assert result == []
