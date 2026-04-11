"""Langfuse observability integration (v4 SDK).

Provides tracing for workflows, agent steps, and LLM calls. Uses the
null-object pattern so instrumentation code is unconditional — when
Langfuse is not configured, every call is a silent no-op.

Trace hierarchy per user message::

    Trace (root span "chat")
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

import hashlib
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


def _to_trace_id(uuid_str: str) -> str:
    """Convert a UUID string to a 32-char lowercase hex Langfuse trace ID."""
    return hashlib.md5(uuid_str.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Null objects — absorb all method calls when Langfuse is off
# ---------------------------------------------------------------------------


class _NullSpan:
    """No-op span that mimics Langfuse span interface."""

    @property
    def id(self) -> str:
        return ""

    @property
    def trace_id(self) -> str:
        return ""

    def start_observation(self, **kwargs: Any) -> _NullSpan:
        return self

    def end(self, **kwargs: Any) -> _NullSpan:
        return self

    def update(self, **kwargs: Any) -> _NullSpan:
        return self

    def score(self, **kwargs: Any) -> None:
        pass

    def score_trace(self, **kwargs: Any) -> None:
        pass


class _NullGeneration(_NullSpan):
    """No-op generation that mimics Langfuse generation interface."""


_NULL_SPAN = _NullSpan()


# ---------------------------------------------------------------------------
# TracingContext — attached to WorkflowState as state._tracing
# ---------------------------------------------------------------------------


class TracingContext:
    """Wraps a Langfuse root span and provides helpers for child observations.

    In Langfuse v4, traces are implicit — created when the first
    observation is started with a ``trace_context``. We create a root
    span named "chat" as the parent of all agent step spans.
    """

    def __init__(self, *, client: Any, root_span: Any) -> None:
        self._client = client
        self._root_span = root_span  # LangfuseSpan or _NullSpan
        self._trace_id = root_span.trace_id if hasattr(root_span, "trace_id") else ""

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
            return cls(client=None, root_span=_NULL_SPAN)

        from langfuse.types import TraceContext

        lf_trace_id = _to_trace_id(trace_id)
        tc = TraceContext(trace_id=lf_trace_id)

        root_span = client.start_observation(
            trace_context=tc,
            name=name,
            as_type="span",
            metadata={
                "user_id": user_id,
                "session_id": session_id,
                "workflow_trace_id": trace_id,
            },
        )
        return cls(client=client, root_span=root_span)

    @property
    def is_active(self) -> bool:
        return self._client is not None

    def span(self, *, name: str, metadata: dict[str, Any] | None = None) -> Any:
        """Create a child span under the root span."""
        if not self.is_active:
            return _NULL_SPAN

        return self._root_span.start_observation(
            name=name,
            as_type="span",
            metadata=metadata or {},
        )

    def generation(self, *, name: str, model: str, input_data: Any = None) -> Any:
        """Create a generation (LLM call) under the root span."""
        if not self.is_active:
            return _NullGeneration()

        return self._root_span.start_observation(
            name=name,
            as_type="generation",
            model=model,
            input=input_data,
        )

    def score(self, *, name: str, value: float, comment: str = "") -> None:
        """Attach a score to the trace."""
        if not self.is_active:
            return

        self._root_span.score_trace(name=name, value=value, comment=comment)

    def end(self) -> None:
        """End the root span."""
        if self.is_active:
            self._root_span.end()

    def flush(self) -> None:
        """End root span and flush pending events to Langfuse."""
        self.end()
        if self._client is not None:
            self._client.flush()


# ---------------------------------------------------------------------------
# LLM call tracing — wraps Claude messages.create()
# ---------------------------------------------------------------------------


@asynccontextmanager
async def null_llm_trace() -> AsyncIterator[_NullGeneration]:
    """No-op async context manager matching trace_llm_call interface."""
    yield _NullGeneration()


@asynccontextmanager
async def trace_llm_call(
    tracing: TracingContext,
    *,
    name: str,
    model: str,
    input_data: Any = None,
) -> AsyncIterator[Any]:
    """Async context-manager that records a Claude API call as a Langfuse generation.

    Usage::

        async with trace_llm_call(tracing, name="planner.llm", model=model, input_data=msg) as gen:
            response = await client.messages.create(...)
            gen.update(output=..., usage_details={...}).end()
    """
    gen = tracing.generation(name=name, model=model, input_data=input_data)
    try:
        yield gen
    except Exception as exc:
        gen.update(status_message=f"error: {exc}", level="ERROR")
        gen.end()
        raise


# ---------------------------------------------------------------------------
# Agent step tracing — wraps agent.run() in the orchestrator
# ---------------------------------------------------------------------------


@contextmanager
def trace_agent_step(
    tracing: TracingContext | None, *, agent_name: str, step_name: str
) -> Iterator[Any]:
    """Sync context-manager that opens/closes a span for an agent step."""
    if tracing is None:
        yield _NULL_SPAN
        return

    span = tracing.span(name=agent_name, metadata={"step": step_name})
    try:
        yield span
    except Exception as exc:
        span.update(status_message=f"error: {exc}", level="ERROR")
        span.end()
        raise
    else:
        span.end()
