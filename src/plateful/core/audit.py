"""Audit callback factory for the orchestrator.

Creates an ``audit_fn`` that writes AuditTrail rows to Postgres after
each agent step.  The function also serialises output safely — agent
results can contain arbitrary objects that are not JSON-serialisable.
"""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from plateful.db.audit_store import log_audit

logger = structlog.get_logger()


def _safe_json(obj: Any) -> dict[str, Any]:
    """Convert arbitrary agent output to a JSON-safe dict."""
    if isinstance(obj, dict):
        return obj
    if obj is None:
        return {}
    try:
        return {"value": str(obj)}
    except Exception:
        return {"value": "<unserializable>"}


def make_audit_fn(session: AsyncSession) -> Any:
    """Return an async audit callback compatible with ``run_workflow``.

    The callback signature matches what the orchestrator expects::

        audit_fn(trace_id=..., step=..., agent=..., snapshot=..., output=...)
    """

    async def _audit(
        *,
        trace_id: str,
        step: str,
        agent: str,
        snapshot: dict[str, Any],
        output: Any,
    ) -> None:
        try:
            await log_audit(
                session,
                trace_id=trace_id,
                user_id=snapshot.get("user_id", ""),
                agent=agent,
                step=step,
                input_snapshot=snapshot,
                output_snapshot=_safe_json(output),
            )
        except Exception:
            # Audit must never break the pipeline; rollback so the session
            # remains usable for subsequent audit calls and the final commit.
            logger.warning("audit_write_failed", trace_id=trace_id, agent=agent, exc_info=True)
            try:
                await session.rollback()
            except Exception:
                pass

    return _audit
