"""Langfuse observability integration.

Provides tracing for workflows, agent steps, and LLM calls. Uses the
null-object pattern so instrumentation code is unconditional — when
Langfuse is not configured, every call is a silent no-op.

Trace hierarchy per user message::

    Trace (name="chat", user_id, session_id)
      ├── Span "planner"
      │     └── Generation "planner.llm" (token usage)
      ├── Span "memory"
      ├── Span "menu"
      ├── Span "recommendation"
      │     └── Generation "recommendation.llm" (token usage)
      ├── Span "execution"
      └── Span "learning"
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any

import structlog

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Langfuse client singleton
# ---------------------------------------------------------------------------

_langfuse_client: Any = None
_langfuse_initialized = False


def get_langfuse() -> Any:
    """Return a Langfuse client, or None if not configured."""
    global _langfuse_client, _langfuse_initialized
    if _langfuse_initialized:
        return _langfuse_client

    _langfuse_initialized = True

    try:
        from langfuse import Langfuse

        from plateful.core.config import settings

        if settings.langfuse_public_key and settings.langfuse_secret_key:
            _langfuse_client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
            logger.info("langfuse_initialized", host=settings.langfuse_host)
        else:
            logger.info("langfuse_disabled", reason="no keys configured")

    except ImportError:
        logger.info("langfuse_disabled", reason="langfuse package not installed")
    except Exception:
        logger.warning("langfuse_init_failed", exc_info=True)

    return _langfuse_client


# ---------------------------------------------------------------------------
# Null objects — absorb all method calls when Langfuse is off
# ---------------------------------------------------------------------------


class _NullSpan:
    """No-op span that mimics Langfuse span interface."""

    def span(self, **kwargs: Any) -> _NullSpan:
        return self

    def generation(self, **kwargs: Any) -> _NullGeneration:
        return _NullGeneration()

    def end(self, **kwargs: Any) -> None:
        pass

    def update(self, **kwargs: Any) -> None:
        pass

    def score(self, **kwargs: Any) -> None:
        pass


class _NullGeneration:
    """No-op generation that mimics Langfuse generation interface."""

    def end(self, **kwargs: Any) -> None:
        pass

    def update(self, **kwargs: Any) -> None:
        pass


class _NullTrace:
    """No-op trace that mimics Langfuse trace interface."""

    def span(self, **kwargs: Any) -> _NullSpan:
        return _NullSpan()

    def generation(self, **kwargs: Any) -> _NullGeneration:
        return _NullGeneration()

    def update(self, **kwargs: Any) -> None:
        pass

    def score(self, **kwargs: Any) -> None:
        pass

    @property
    def id(self) -> str:
        return ""


_NULL_TRACE = _NullTrace()
_NULL_SPAN = _NullSpan()


# ---------------------------------------------------------------------------
# TracingContext — attached to WorkflowState as state._tracing
# ---------------------------------------------------------------------------


class TracingContext:
    """Wraps a Langfuse trace and provides helpers for spans and generations."""

    def __init__(self, trace: Any) -> None:
        self._trace = trace

    @classmethod
    def create(
        cls,
        *,
        trace_id: str,
        user_id: str,
        session_id: str,
        name: str = "chat",
    ) -> TracingContext:
        """Create a tracing context. Returns a null context if Langfuse is off."""
        client = get_langfuse()
        if client is None:
            return cls(trace=_NULL_TRACE)

        trace = client.trace(
            id=trace_id,
            name=name,
            user_id=user_id,
            session_id=session_id,
        )
        return cls(trace=trace)

    @property
    def trace(self) -> Any:
        return self._trace

    @property
    def is_active(self) -> bool:
        return not isinstance(self._trace, _NullTrace)

    def span(self, *, name: str, metadata: dict[str, Any] | None = None) -> Any:
        """Create a child span on the trace."""
        return self._trace.span(name=name, metadata=metadata or {})

    def score(self, *, name: str, value: float, comment: str = "") -> None:
        """Attach a score to the trace."""
        self._trace.score(name=name, value=value, comment=comment)

    def flush(self) -> None:
        """Flush pending events to Langfuse."""
        client = get_langfuse()
        if client is not None:
            client.flush()


# ---------------------------------------------------------------------------
# LLM call tracing — wraps Claude messages.create()
# ---------------------------------------------------------------------------


@asynccontextmanager
async def null_llm_trace() -> AsyncIterator[_NullGeneration]:
    """No-op async context manager matching trace_llm_call interface."""
    yield _NullGeneration()


@asynccontextmanager
async def trace_llm_call(
    parent: Any,
    *,
    name: str,
    model: str,
    input_data: Any = None,
) -> AsyncIterator[Any]:
    """Async context-manager that records a Claude API call as a Langfuse generation.

    Usage::

        async with trace_llm_call(span, name="planner.llm", model=model, input_data=msg) as gen:
            response = await client.messages.create(...)
            gen.end(
                output=response.content[0].text,
                usage={"input": response.usage.input_tokens, "output": response.usage.output_tokens},
            )

    ``parent`` can be a Langfuse span, trace, or a null object.
    """
    gen = parent.generation(name=name, model=model, input=input_data)
    try:
        yield gen
    except Exception as exc:
        gen.end(status_message=f"error: {exc}", level="ERROR")
        raise


# ---------------------------------------------------------------------------
# Agent step tracing — wraps agent.run() in the orchestrator
# ---------------------------------------------------------------------------


@contextmanager
def trace_agent_step(
    tracing: TracingContext | None, *, agent_name: str, step_name: str
) -> Iterator[Any]:
    """Sync context-manager that opens/closes a span for an agent step.

    Used in the orchestrator step loop. Yields the span object so callers
    can attach child generations or metadata.
    """
    if tracing is None:
        yield _NULL_SPAN
        return

    span = tracing.span(name=agent_name, metadata={"step": step_name})
    try:
        yield span
    except Exception as exc:
        span.end(status_message=f"error: {exc}", level="ERROR")
        raise
    else:
        span.end()
