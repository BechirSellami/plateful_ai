"""Unit tests for the WebSocket chat handler."""

from typing import Any

import pytest

from plateful.agents.planner import PlannerAgent
from plateful.api.ws import websocket_chat
from plateful.core.workflow import WorkflowState


class FakeWebSocket:
    """Minimal fake WebSocket for testing the handler."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._incoming = list(messages)
        self.sent: list[dict[str, Any]] = []
        self._call_count = 0

    async def accept(self) -> None:
        pass

    async def receive_json(self) -> dict[str, Any]:
        if self._call_count >= len(self._incoming):
            from fastapi import WebSocketDisconnect

            raise WebSocketDisconnect(code=1000)
        msg = self._incoming[self._call_count]
        self._call_count += 1
        return msg

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


class FakeAgent:
    """Agent that records calls and returns state unchanged."""

    def __init__(self, intent: str | None = None) -> None:
        self.called = False
        self._intent = intent

    async def run(self, state: WorkflowState) -> WorkflowState:
        self.called = True
        if self._intent:
            state.intent = self._intent
        return state


def _keyword_planner() -> PlannerAgent:
    return PlannerAgent(mode="keyword")


@pytest.mark.unit
class TestWebSocketChat:
    async def test_sends_step_and_result_messages(self) -> None:
        ws = FakeWebSocket([{"message": "hello", "user_id": "u1", "session_id": "s1"}])
        registry: dict[str, Any] = {
            "menu": FakeAgent(),
            "recommendation": FakeAgent(),
        }

        await websocket_chat(ws, registry, _keyword_planner())  # type: ignore[arg-type]

        types = [m["type"] for m in ws.sent]
        assert "step" in types
        assert "result" in types

    async def test_result_contains_intent(self) -> None:
        ws = FakeWebSocket([{"message": "order lunch", "user_id": "u1", "session_id": "s1"}])
        registry: dict[str, Any] = {
            "menu": FakeAgent(),
            "recommendation": FakeAgent(),
        }

        await websocket_chat(ws, registry, _keyword_planner())  # type: ignore[arg-type]

        result = next(m for m in ws.sent if m["type"] == "result")
        assert result["intent"] == "order_meal"

    async def test_empty_message_returns_error(self) -> None:
        ws = FakeWebSocket([{"message": "", "user_id": "u1", "session_id": "s1"}])
        registry: dict[str, Any] = {}

        await websocket_chat(ws, registry, _keyword_planner())  # type: ignore[arg-type]

        assert ws.sent[0]["type"] == "error"
        assert "Empty" in ws.sent[0]["detail"]

    async def test_multiple_messages_in_session(self) -> None:
        ws = FakeWebSocket(
            [
                {"message": "hi", "user_id": "u1", "session_id": "s1"},
                {"message": "order pasta", "user_id": "u1", "session_id": "s1"},
            ]
        )
        registry: dict[str, Any] = {
            "menu": FakeAgent(),
            "recommendation": FakeAgent(),
        }

        await websocket_chat(ws, registry, _keyword_planner())  # type: ignore[arg-type]

        results = [m for m in ws.sent if m["type"] == "result"]
        assert len(results) == 2

    async def test_pipeline_error_sends_error_message(self) -> None:
        class BrokenAgent:
            async def run(self, state: WorkflowState) -> WorkflowState:
                msg = "boom"
                raise RuntimeError(msg)

        ws = FakeWebSocket([{"message": "order lunch", "user_id": "u1", "session_id": "s1"}])
        registry: dict[str, Any] = {"menu": BrokenAgent(), "recommendation": FakeAgent()}

        await websocket_chat(ws, registry, _keyword_planner())  # type: ignore[arg-type]

        # First message is "plan" step, then error from broken agent
        assert ws.sent[0]["type"] == "step"
        error_msgs = [m for m in ws.sent if m["type"] == "error"]
        assert len(error_msgs) >= 1

    async def test_defaults_user_and_session(self) -> None:
        ws = FakeWebSocket([{"message": "hi"}])
        registry: dict[str, Any] = {
            "menu": FakeAgent(),
            "recommendation": FakeAgent(),
        }

        await websocket_chat(ws, registry, _keyword_planner())  # type: ignore[arg-type]

        result = next(m for m in ws.sent if m["type"] == "result")
        assert result["type"] == "result"
