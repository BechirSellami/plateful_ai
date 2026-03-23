"""Policy Agent: validates budget, compliance rules, routes for approval if needed.

Deterministic validation — no LLM involved. Budget caps and approval thresholds
are enforced strictly based on department policy rules.
"""

from typing import Any

import structlog

from plateful.core.workflow import WorkflowState
from plateful.tools.policy_tools import validate_order

logger = structlog.get_logger()


class PolicyAgent:
    """Validate orders against department rules. Deterministic, never LLM."""

    def __init__(self, policies: list[dict[str, Any]] | None = None) -> None:
        self._policies = policies

    async def run(self, state: WorkflowState) -> WorkflowState:
        order_total = self._calculate_order_total(state)

        result = validate_order(
            order_total=order_total,
            item_count=len(state.recommendations) or 1,
            policies=self._policies,
        )

        state.policy_result = result
        state.requires_approval = result["requires_approval"]
        state.last_result = result

        logger.info(
            "policy_agent_complete",
            trace_id=state.trace_id,
            order_total=order_total,
            passed=result["passed"],
            requires_approval=result["requires_approval"],
            violations_count=len(result["violations"]),
        )

        return state

    def _calculate_order_total(self, state: WorkflowState) -> float:
        """Calculate total from recommendations or menu items."""
        items = state.recommendations or state.menu_items
        if not items:
            return 0.0

        # If we have specific recommendations, sum their prices
        # Otherwise use the first item as a single-meal estimate
        if state.recommendations:
            # For a single meal order, use the top recommendation
            top = state.recommendations[0]
            return float(top.get("price_usd", 0))

        return sum(float(item.get("price_usd", 0)) for item in items)
