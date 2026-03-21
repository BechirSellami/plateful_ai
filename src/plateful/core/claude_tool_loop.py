import inspect
import json
from collections.abc import Callable
from typing import Any

import anthropic
import structlog

logger = structlog.get_logger()


def to_claude_tool_schema(func: Callable[..., Any]) -> dict[str, Any]:
    """Convert a Python function to a Claude tool definition using its docstring and type hints."""
    hints = func.__annotations__
    properties: dict[str, Any] = {}
    required: list[str] = []

    params = inspect.signature(func).parameters
    for name, param in params.items():
        if name in ("self", "cls"):
            continue
        prop: dict[str, Any] = {"type": "string"}
        hint = hints.get(name)
        if hint is int:
            prop = {"type": "integer"}
        elif hint is float:
            prop = {"type": "number"}
        elif hint is bool:
            prop = {"type": "boolean"}
        elif hint is list or (
            hasattr(hint, "__origin__") and getattr(hint, "__origin__", None) is list
        ):
            prop = {"type": "array", "items": {"type": "string"}}
        elif hint is dict:
            prop = {"type": "object"}

        prop["description"] = f"Parameter: {name}"
        properties[name] = prop

        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "name": func.__name__,
        "description": (func.__doc__ or f"Tool: {func.__name__}").strip(),
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": required,
        },
    }


async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    tools: list[Callable[..., Any]],
) -> Any:
    """Execute a tool by name with given input."""
    tool_map = {t.__name__: t for t in tools}
    func = tool_map.get(tool_name)
    if not func:
        return f"Error: Unknown tool '{tool_name}'"

    try:
        result = func(**tool_input)
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception as e:
        logger.exception("tool_execution_failed", tool=tool_name)
        return f"Error executing {tool_name}: {e}"


async def claude_tool_loop(
    *,
    client: anthropic.AsyncAnthropic,
    system: str,
    context: dict[str, Any],
    tools: list[Callable[..., Any]],
    model: str = "claude-sonnet-4-20250514",
    max_iterations: int = 10,
) -> Any:
    """Run a tool-use loop with Claude until it returns a final text response."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": json.dumps(context, default=str)},
    ]
    tool_defs = [to_claude_tool_schema(t) for t in tools]

    for iteration in range(max_iterations):
        response = await client.messages.create(
            model=model,
            system=system,
            messages=messages,  # type: ignore[arg-type]
            tools=tool_defs,  # type: ignore[arg-type]
            max_tokens=2048,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if block.type == "text":
                    return block.text
            return None

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                logger.info(
                    "tool_call",
                    tool=block.name,
                    iteration=iteration,
                )
                result = await execute_tool(block.name, block.input, tools)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    }
                )

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    logger.warning("tool_loop_max_iterations", max_iterations=max_iterations)
    return None
