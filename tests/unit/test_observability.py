"""Unit tests for the observability module (Langfuse integration)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from plateful.core.observability import (
    TracingContext,
    _NullGeneration,
    _NullSpan,
    _NullTrace,
    null_llm_trace,
    trace_agent_step,
    trace_llm_call,
)
from plateful.core.workflow import WorkflowState


def _make_state(message: str = "hello") -> WorkflowState:
    return WorkflowState(
        user_id="emp_123",
        session_id="sess_1",
        messages=[{"content": message}],
    )


# ---------------------------------------------------------------------------
# Null objects
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNullObjects:
    def test_null_span_is_noop(self) -> None:
        span = _NullSpan()
        child = span.span(name="child")
        assert isinstance(child, _NullSpan)
        gen = span.generation(name="gen")
        assert isinstance(gen, _NullGeneration)
        span.end()
        span.update(metadata={"x": 1})
        span.score(name="test", value=1.0)

    def test_null_generation_is_noop(self) -> None:
        gen = _NullGeneration()
        gen.end(output="text", usage={"input": 10, "output": 5})
        gen.update(metadata={"x": 1})

    def test_null_trace_is_noop(self) -> None:
        trace = _NullTrace()
        span = trace.span(name="test")
        assert isinstance(span, _NullSpan)
        gen = trace.generation(name="test")
        assert isinstance(gen, _NullGeneration)
        trace.update(metadata={"x": 1})
        trace.score(name="test", value=1.0)
        assert trace.id == ""


# ---------------------------------------------------------------------------
# get_langfuse()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetLangfuse:
    def test_returns_none_when_keys_missing(self) -> None:
        import plateful.core.observability as obs

        # Reset singleton
        obs._langfuse_initialized = False
        obs._langfuse_client = None

        with patch.object(obs, "get_langfuse", wraps=obs.get_langfuse):
            # Settings have empty keys by default in test env
            client = obs.get_langfuse()
            assert client is None

        # Reset for other tests
        obs._langfuse_initialized = False
        obs._langfuse_client = None

    def test_returns_client_when_keys_present(self) -> None:
        import plateful.core.observability as obs

        obs._langfuse_initialized = False
        obs._langfuse_client = None

        mock_settings = MagicMock()
        mock_settings.langfuse_public_key = "pk-test"
        mock_settings.langfuse_secret_key = "sk-test"
        mock_settings.langfuse_host = "https://test.langfuse.com"

        mock_langfuse_cls = MagicMock()
        mock_client = MagicMock()
        mock_langfuse_cls.return_value = mock_client

        with (
            patch("plateful.core.config.settings", mock_settings),
            patch.dict("sys.modules", {"langfuse": MagicMock(Langfuse=mock_langfuse_cls)}),
        ):
            obs._langfuse_initialized = False
            obs._langfuse_client = None
            obs.get_langfuse()

        # Reset
        obs._langfuse_initialized = False
        obs._langfuse_client = None


# ---------------------------------------------------------------------------
# TracingContext
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTracingContext:
    def test_create_returns_null_when_langfuse_off(self) -> None:
        with patch("plateful.core.observability.get_langfuse", return_value=None):
            ctx = TracingContext.create(trace_id="t1", user_id="u1", session_id="s1")
            assert not ctx.is_active
            # Span returns a null span
            span = ctx.span(name="test")
            assert isinstance(span, _NullSpan)

    def test_create_returns_active_when_langfuse_on(self) -> None:
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.trace.return_value = mock_trace

        with patch("plateful.core.observability.get_langfuse", return_value=mock_client):
            ctx = TracingContext.create(trace_id="t1", user_id="u1", session_id="s1")
            assert ctx.is_active
            mock_client.trace.assert_called_once_with(
                id="t1", name="chat", user_id="u1", session_id="s1"
            )

    def test_span_delegates_to_trace(self) -> None:
        mock_trace = MagicMock()
        ctx = TracingContext(trace=mock_trace)
        ctx.span(name="test_agent", metadata={"step": "test"})
        mock_trace.span.assert_called_once_with(name="test_agent", metadata={"step": "test"})

    def test_score_delegates_to_trace(self) -> None:
        mock_trace = MagicMock()
        ctx = TracingContext(trace=mock_trace)
        ctx.score(name="accuracy", value=0.95, comment="good")
        mock_trace.score.assert_called_once_with(name="accuracy", value=0.95, comment="good")

    def test_flush_calls_langfuse_flush(self) -> None:
        mock_client = MagicMock()
        with patch("plateful.core.observability.get_langfuse", return_value=mock_client):
            ctx = TracingContext(trace=MagicMock())
            ctx.flush()
            mock_client.flush.assert_called_once()


# ---------------------------------------------------------------------------
# trace_llm_call
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTraceLlmCall:
    async def test_creates_generation_and_yields(self) -> None:
        mock_parent = MagicMock()
        mock_gen = MagicMock()
        mock_parent.generation.return_value = mock_gen

        async with trace_llm_call(
            mock_parent, name="test.llm", model="claude-test", input_data="hello"
        ) as gen:
            assert gen is mock_gen

        mock_parent.generation.assert_called_once_with(
            name="test.llm", model="claude-test", input="hello"
        )

    async def test_ends_with_error_on_exception(self) -> None:
        mock_parent = MagicMock()
        mock_gen = MagicMock()
        mock_parent.generation.return_value = mock_gen

        with pytest.raises(ValueError, match="boom"):
            async with trace_llm_call(mock_parent, name="test.llm", model="m", input_data="x"):
                raise ValueError("boom")

        mock_gen.end.assert_called_once()
        call_kwargs = mock_gen.end.call_args.kwargs
        assert "error" in call_kwargs["status_message"]

    async def test_null_llm_trace_is_noop(self) -> None:
        async with null_llm_trace() as gen:
            assert isinstance(gen, _NullGeneration)
            gen.end(output="text", usage={"input": 10})


# ---------------------------------------------------------------------------
# trace_agent_step
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTraceAgentStep:
    def test_creates_span_when_tracing_active(self) -> None:
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_trace.span.return_value = mock_span
        ctx = TracingContext(trace=mock_trace)

        with trace_agent_step(ctx, agent_name="menu", step_name="retrieve") as span:
            assert span is mock_span

        mock_trace.span.assert_called_once_with(name="menu", metadata={"step": "retrieve"})
        mock_span.end.assert_called_once()

    def test_returns_null_span_when_tracing_none(self) -> None:
        with trace_agent_step(None, agent_name="menu", step_name="retrieve") as span:
            assert isinstance(span, _NullSpan)

    def test_ends_with_error_on_exception(self) -> None:
        mock_trace = MagicMock()
        mock_span = MagicMock()
        mock_trace.span.return_value = mock_span
        ctx = TracingContext(trace=mock_trace)

        with (
            pytest.raises(RuntimeError, match="fail"),
            trace_agent_step(ctx, agent_name="menu", step_name="retrieve"),
        ):
            raise RuntimeError("fail")

        mock_span.end.assert_called_once()
        call_kwargs = mock_span.end.call_args.kwargs
        assert "error" in call_kwargs["status_message"]


# ---------------------------------------------------------------------------
# Orchestrator integration (tracing attached to state)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOrchestratorTracing:
    async def test_run_planned_workflow_creates_trace(self) -> None:
        from plateful.core.orchestrator import run_planned_workflow

        call_order: list[str] = []

        class RecordingAgent:
            def __init__(self, name: str) -> None:
                self.name = name

            async def run(self, state: WorkflowState) -> WorkflowState:
                call_order.append(self.name)
                # Verify tracing is attached
                assert hasattr(state, "_tracing")
                return state

        registry: dict[str, Any] = {
            "menu": RecordingAgent("menu"),
            "recommendation": RecordingAgent("recommendation"),
        }

        # Mock planner
        class MockPlanner:
            async def plan(self, state: WorkflowState, available: set[str]) -> dict[str, Any]:
                return {
                    "intent": "get_recommendation",
                    "constraints": {},
                    "plan": [
                        {"agent": "menu", "reason": "Get menu"},
                        {"agent": "recommendation", "reason": "Suggest"},
                    ],
                }

        state = _make_state("Recommend something")

        with patch("plateful.core.observability.get_langfuse", return_value=None):
            await run_planned_workflow(state, registry, MockPlanner())

        assert call_order == ["menu", "recommendation"]
