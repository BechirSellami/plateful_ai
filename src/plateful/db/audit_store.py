"""Audit trail persistence — write and query audit records.

Each agent step in the orchestrator pipeline writes an AuditTrail row
capturing the decision context: what agent ran, what it saw (input
snapshot), what it produced (output snapshot), and the outcome.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from plateful.db.models import AuditOutcome, AuditTrail, DecisionType

# Map agent names to decision types for structured categorisation.
_AGENT_DECISION_MAP: dict[str, DecisionType] = {
    "recommendation": DecisionType.RECOMMENDATION,
    "menu": DecisionType.ALLERGY_FILTER,
    "policy": DecisionType.POLICY_CHECK,
    "execution": DecisionType.ORDER_SUBMIT,
}

_AGENT_OUTCOME_MAP: dict[str, AuditOutcome] = {
    "execution": AuditOutcome.ACCEPTED,
    "policy": AuditOutcome.PENDING,
}


def _infer_decision_type(agent: str, output: Any) -> DecisionType:
    """Infer decision type from agent name."""
    return _AGENT_DECISION_MAP.get(agent, DecisionType.RECOMMENDATION)


def _infer_outcome(agent: str, output: Any) -> AuditOutcome:
    """Infer outcome from agent name and output."""
    if agent == "policy" and isinstance(output, dict):
        if output.get("violations"):
            return AuditOutcome.REJECTED
        return AuditOutcome.ACCEPTED
    return _AGENT_OUTCOME_MAP.get(agent, AuditOutcome.ACCEPTED)


async def log_audit(
    session: AsyncSession,
    *,
    trace_id: str,
    user_id: str,
    agent: str,
    step: str,
    input_snapshot: dict[str, Any],
    output_snapshot: dict[str, Any],
    reasoning: str | None = None,
    decision_type: DecisionType | None = None,
    outcome: AuditOutcome | None = None,
) -> AuditTrail:
    """Write a single audit trail row."""
    record = AuditTrail(
        id=uuid.uuid4(),
        trace_id=uuid.UUID(trace_id),
        user_id=user_id,
        agent=agent,
        decision_type=decision_type or _infer_decision_type(agent, output_snapshot),
        input_snapshot=input_snapshot,
        output_snapshot=output_snapshot,
        reasoning=reasoning or f"Agent '{agent}' executed step '{step}'",
        outcome=outcome or _infer_outcome(agent, output_snapshot),
    )
    session.add(record)
    await session.flush()
    return record


async def get_trace_audit(
    session: AsyncSession,
    *,
    trace_id: str,
) -> list[AuditTrail]:
    """Return all audit rows for a trace, ordered chronologically."""
    stmt = (
        select(AuditTrail)
        .where(AuditTrail.trace_id == uuid.UUID(trace_id))
        .order_by(AuditTrail.timestamp)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_user_audit(
    session: AsyncSession,
    *,
    user_id: str,
    since: datetime | None = None,
    limit: int = 50,
) -> list[AuditTrail]:
    """Return audit rows for a user, most recent first."""
    stmt = select(AuditTrail).where(AuditTrail.user_id == user_id)
    if since:
        stmt = stmt.where(AuditTrail.timestamp >= since)
    stmt = stmt.order_by(AuditTrail.timestamp.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
