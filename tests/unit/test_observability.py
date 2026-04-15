"""Unit tests for the observability module (Langfuse integration)."""

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from plateful.core.observability import (
    TracingContext,
    _NullGeneration,
    _NullSpan,
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
        child = span.start_observation(name="child")
        assert isinstance(child, _NullSpan)
        span.end()
        span.update(metadata={"x": 1})
        span.score(name="test", value=1.0)
        assert span.id == ""
        assert span.trace_id == ""

    def test_null_generation_is_noop(self) -> None:
        gen = _NullGeneration()
        gen.end(output="text", usage_details={"input": 10, "output": 5})
        gen.update(metadata={"x": 1})


# ---------------------------------------------------------------------------
# get_langfuse()
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetLangfuse:
    def test_returns_none_when_keys_missing(self) -> None:
        import plateful.core.observability as obs

        obs._langfuse_initialized = False
        obs._langfuse_client = None

        mock_settings = MagicMock()
        mock_settings.langfuse_public_key = ""
        mock_settings.langfuse_secret_key = ""

        with patch("plateful.core.config.settings", mock_settings):
            client = obs.get_langfuse()
            assert client is None

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
            span = ctx.span(name="test")
            assert isinstance(span, _NullSpan)

    def test_create_returns_active_when_langfuse_on(self) -> None:
        mock_client = MagicMock()
        mock_root_span = MagicMock()
        mock_client.start_observation.return_value = mock_root_span

        # Provide a fake langfuse.types module so the deferred import
        # inside TracingContext.create succeeds even when langfuse is
        # not installed (e.g. in CI).
        mock_types = MagicMock()
        with (
            patch.dict("sys.modules", {"langfuse": MagicMock(), "langfuse.types": mock_types}),
            patch("plateful.core.observability.get_langfuse", return_value=mock_client),
        ):
            ctx = TracingContext.create(trace_id="t1", user_id="u1", session_id="s1")
            assert ctx.is_active

    def test_span_calls_start_observation_on_root(self) -> None:
        mock_root_span = MagicMock()
        mock_child_span = MagicMock()
        mock_root_span.start_observation.return_value = mock_child_span

        ctx = TracingContext(client=MagicMock(), root_span=mock_root_span)
        result = ctx.span(name="test_agent", metadata={"step": "test"})

        mock_root_span.start_observation.assert_called_once_with(
            name="test_agent",
            as_type="span",
            metadata={"step": "test"},
        )
        assert result is mock_child_span

    def test_generation_calls_start_observation_on_root(self) -> None:
        mock_root_span = MagicMock()
        mock_gen = MagicMock()
        mock_root_span.start_observation.return_value = mock_gen

        ctx = TracingContext(client=MagicMock(), root_span=mock_root_span)
        result = ctx.generation(name="test.llm", model="claude-test", input_data="hello")

        mock_root_span.start_observation.assert_called_once_with(
            name="test.llm",
            as_type="generation",
            model="claude-test",
            input="hello",
        )
        assert result is mock_gen

    def test_score_calls_score_trace_on_root(self) -> None:
        mock_root_span = MagicMock()
        ctx = TracingContext(client=MagicMock(), root_span=mock_root_span)
        ctx.score(name="accuracy", value=0.95, comment="good")
        mock_root_span.score_trace.assert_called_once_with(
            name="accuracy", value=0.95, comment="good"
        )

    def test_flush_calls_client_flush(self) -> None:
        mock_client = MagicMock()
        mock_root_span = MagicMock()
        ctx = TracingContext(client=mock_client, root_span=mock_root_span)
        ctx.flush()
        mock_root_span.end.assert_called_once()
        mock_client.flush.assert_called_once()

    def test_null_context_score_is_noop(self) -> None:
        ctx = TracingContext(client=None, root_span=_NullSpan())
        ctx.score(name="test", value=1.0)  # should not raise

    def test_null_context_flush_is_noop(self) -> None:
        ctx = TracingContext(client=None, root_span=_NullSpan())
        ctx.flush()  # should not raise


# ---------------------------------------------------------------------------
# trace_llm_call
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTraceLlmCall:
    async def test_creates_generation_and_yields(self) -> None:
        mock_root_span = MagicMock()
        mock_gen = MagicMock()
        mock_root_span.start_observation.return_value = mock_gen

        ctx = TracingContext(client=MagicMock(), root_span=mock_root_span)

        async with trace_llm_call(
            ctx, name="test.llm", model="claude-test", input_data="hello"
        ) as gen:
            assert gen is mock_gen

    async def test_ends_with_error_on_exception(self) -> None:
        mock_root_span = MagicMock()
        mock_gen = MagicMock()
        mock_root_span.start_observation.return_value = mock_gen

        ctx = TracingContext(client=MagicMock(), root_span=mock_root_span)

        with pytest.raises(ValueError, match="boom"):
            async with trace_llm_call(ctx, name="test.llm", model="m", input_data="x"):
                raise ValueError("boom")

        mock_gen.update.assert_called_once()
        call_kwargs = mock_gen.update.call_args.kwargs
        assert "error" in call_kwargs["status_message"]
        mock_gen.end.assert_called_once()

    async def test_null_llm_trace_is_noop(self) -> None:
        async with null_llm_trace() as gen:
            assert isinstance(gen, _NullGeneration)
            gen.end(output="text", usage_details={"input": 10})


# ---------------------------------------------------------------------------
# trace_agent_step
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTraceAgentStep:
    def test_creates_span_when_tracing_active(self) -> None:
        mock_root_span = MagicMock()
        mock_child_span = MagicMock()
        mock_root_span.start_observation.return_value = mock_child_span

        ctx = TracingContext(client=MagicMock(), root_span=mock_root_span)

        with trace_agent_step(ctx, agent_name="menu", step_name="retrieve") as span:
            assert span is mock_child_span

        mock_child_span.end.assert_called_once()

    def test_returns_null_span_when_tracing_none(self) -> None:
        with trace_agent_step(None, agent_name="menu", step_name="retrieve") as span:
            assert isinstance(span, _NullSpan)

    def test_ends_with_error_on_exception(self) -> None:
        mock_root_span = MagicMock()
        mock_child_span = MagicMock()
        mock_root_span.start_observation.return_value = mock_child_span

        ctx = TracingContext(client=MagicMock(), root_span=mock_root_span)

        with (
            pytest.raises(RuntimeError, match="fail"),
            trace_agent_step(ctx, agent_name="menu", step_name="retrieve"),
        ):
            raise RuntimeError("fail")

        mock_child_span.update.assert_called_once()
        call_kwargs = mock_child_span.update.call_args.kwargs
        assert "error" in call_kwargs["status_message"]
        mock_child_span.end.assert_called_once()


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
                assert hasattr(state, "_tracing")
                return state

        registry: dict[str, Any] = {
            "menu": RecordingAgent("menu"),
            "recommendation": RecordingAgent("recommendation"),
        }

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
