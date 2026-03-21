import pytest

from plateful.core.claude_tool_loop import execute_tool, to_claude_tool_schema


def sample_tool(name: str, count: int = 5) -> str:
    """A sample tool for testing."""
    return f"{name}: {count}"


async def async_sample_tool(query: str) -> list[str]:
    """An async sample tool."""
    return [query]


@pytest.mark.unit
class TestToClaudeToolSchema:
    def test_basic_schema(self) -> None:
        schema = to_claude_tool_schema(sample_tool)
        assert schema["name"] == "sample_tool"
        assert "sample tool" in schema["description"].lower()
        assert "name" in schema["input_schema"]["properties"]
        assert "count" in schema["input_schema"]["properties"]
        assert "name" in schema["input_schema"]["required"]
        assert "count" not in schema["input_schema"]["required"]  # has default

    def test_type_mapping(self) -> None:
        schema = to_claude_tool_schema(sample_tool)
        props = schema["input_schema"]["properties"]
        assert props["name"]["type"] == "string"
        assert props["count"]["type"] == "integer"

    def test_async_tool_schema(self) -> None:
        schema = to_claude_tool_schema(async_sample_tool)
        assert schema["name"] == "async_sample_tool"
        props = schema["input_schema"]["properties"]
        assert props["query"]["type"] == "string"


@pytest.mark.unit
class TestExecuteTool:
    async def test_executes_sync_tool(self) -> None:
        result = await execute_tool("sample_tool", {"name": "test", "count": 3}, [sample_tool])
        assert result == "test: 3"

    async def test_executes_async_tool(self) -> None:
        result = await execute_tool("async_sample_tool", {"query": "hello"}, [async_sample_tool])
        assert result == ["hello"]

    async def test_unknown_tool_returns_error(self) -> None:
        result = await execute_tool("nonexistent", {}, [sample_tool])
        assert "Unknown tool" in str(result)

    async def test_tool_error_returns_message(self) -> None:
        def bad_tool() -> None:
            """A tool that always fails."""
            raise ValueError("boom")

        result = await execute_tool("bad_tool", {}, [bad_tool])
        assert "Error" in str(result)
