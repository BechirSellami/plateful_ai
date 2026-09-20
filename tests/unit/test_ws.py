"""Unit tests for the WebSocket chat handler."""

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

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


@pytest.fixture(autouse=True)
def _mock_deps(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent WebSocket tests from hitting real DB or Langfuse."""

    @asynccontextmanager
    async def _fake_session():
        yield AsyncMock()

    monkeypatch.setattr("plateful.api.ws.async_session_factory", lambda: _fake_session())
    monkeypatch.setattr("plateful.core.observability.get_langfuse", lambda: None)


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


class RecordingPlanner(PlannerAgent):
    """Keyword planner that records ``state.messages`` on every turn.

    The planner is the consumer of the transcript, so it's the right
    place to observe what history the handler carried forward.
    """

    def __init__(self) -> None:
        super().__init__(mode="keyword")
        self.seen_messages: list[list[dict[str, str]]] = []

    async def plan(self, state: WorkflowState, available_agents: set[str]) -> dict[str, Any]:
        self.seen_messages.append([dict(m) for m in state.messages])
        return await super().plan(state, available_agents)


class ReplyAgent:
    """Agent that sets a fixed natural-language reply."""

    def __init__(self, reply: str) -> None:
        self._reply = reply

    async def run(self, state: WorkflowState) -> WorkflowState:
        state.recommendation_text = self._reply
        return state


@pytest.mark.unit
class TestWebSocketConversationHistory:
    async def test_second_turn_sees_first_exchange(self) -> None:
        ws = FakeWebSocket(
            [
                {"message": "what do you recommend?", "user_id": "u1", "session_id": "s1"},
                {"message": "the second one", "user_id": "u1", "session_id": "s1"},
            ]
        )
        planner = RecordingPlanner()
        registry: dict[str, Any] = {
            "menu": FakeAgent(),
            "recommendation": ReplyAgent("1. Pad Thai\n2. Chicken Katsu"),
        }

        await websocket_chat(ws, registry, planner)  # type: ignore[arg-type]

        assert len(planner.seen_messages) == 2
        # Turn 1: just the current message.
        assert planner.seen_messages[0] == [{"role": "user", "content": "what do you recommend?"}]
        # Turn 2: prior user turn, the assistant's rendered reply, then the new message.
        assert planner.seen_messages[1] == [
            {"role": "user", "content": "what do you recommend?"},
            {"role": "assistant", "content": "1. Pad Thai\n2. Chicken Katsu"},
            {"role": "user", "content": "the second one"},
        ]

    async def test_current_message_is_always_last(self) -> None:
        ws = FakeWebSocket(
            [
                {"message": "hi", "user_id": "u1", "session_id": "s1"},
                {"message": "order pasta", "user_id": "u1", "session_id": "s1"},
                {"message": "yes", "user_id": "u1", "session_id": "s1"},
            ]
        )
        planner = RecordingPlanner()
        registry: dict[str, Any] = {"menu": FakeAgent(), "recommendation": FakeAgent()}

        await websocket_chat(ws, registry, planner)  # type: ignore[arg-type]

        for seen, expected in zip(planner.seen_messages, ["hi", "order pasta", "yes"], strict=True):
            assert seen[-1] == {"role": "user", "content": expected}
            # Roles strictly alternate, starting with user.
            roles = [m["role"] for m in seen]
            assert roles == ["user", "assistant"] * (len(roles) // 2) + ["user"]

    async def test_error_turn_is_recorded_so_history_keeps_alternating(self) -> None:
        class FlakyAgent:
            def __init__(self) -> None:
                self.calls = 0

            async def run(self, state: WorkflowState) -> WorkflowState:
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("boom")
                return state

        ws = FakeWebSocket(
            [
                {"message": "order lunch", "user_id": "u1", "session_id": "s1"},
                {"message": "try again", "user_id": "u1", "session_id": "s1"},
            ]
        )
        planner = RecordingPlanner()
        registry: dict[str, Any] = {"menu": FlakyAgent(), "recommendation": FakeAgent()}

        await websocket_chat(ws, registry, planner)  # type: ignore[arg-type]

        assert [m["type"] for m in ws.sent if m["type"] in ("error", "result")] == [
            "error",
            "result",
        ]
        second = planner.seen_messages[1]
        assert [m["role"] for m in second] == ["user", "assistant", "user"]
        assert second[0]["content"] == "order lunch"
        assert second[-1]["content"] == "try again"

    async def test_history_is_capped(self) -> None:
        from plateful.core.conversation import MAX_HISTORY_MESSAGES

        n_turns = MAX_HISTORY_MESSAGES  # 2 messages per turn → well over the cap
        ws = FakeWebSocket(
            [{"message": f"m{i}", "user_id": "u1", "session_id": "s1"} for i in range(n_turns)]
        )
        planner = RecordingPlanner()
        registry: dict[str, Any] = {"menu": FakeAgent(), "recommendation": FakeAgent()}

        await websocket_chat(ws, registry, planner)  # type: ignore[arg-type]

        last = planner.seen_messages[-1]
        # Carried-forward history is capped; plus the current message.
        assert len(last) <= MAX_HISTORY_MESSAGES + 1
        assert last[-1] == {"role": "user", "content": f"m{n_turns - 1}"}
