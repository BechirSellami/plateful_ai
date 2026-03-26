"""Execution Agent: submits orders and sends confirmations.

Completes the happy path by placing the order and notifying the user.
If the policy agent flagged requires_approval, the order is placed in
pending_approval status instead of submitted.
"""

import structlog

from plateful.core.workflow import WorkflowState
from plateful.tools.execution_tools import send_notification, submit_order

logger = structlog.get_logger()


class ExecutionAgent:
    """Submit order, schedule delivery, send confirmation."""

    async def run(self, state: WorkflowState) -> WorkflowState:
        # Check if policy blocked the order
        if state.policy_result and not state.policy_result.get("passed", True):
            violations = state.policy_result.get("violations", [])
            violation_msgs = [v.get("message", "Policy violation") for v in violations]
            state.last_result = {
                "status": "blocked",
                "reason": "Policy violations: " + "; ".join(violation_msgs),
            }
            logger.info(
                "execution_agent_blocked",
                trace_id=state.trace_id,
                violations=violation_msgs,
            )
            return state

        # Get items to order (top recommendation or all recommendations)
        items = state.recommendations[:1] if state.recommendations else state.menu_items[:1]
        if not items:
            state.last_result = {"status": "error", "reason": "No items to order"}
            return state

        total = float(items[0].get("price_usd", 0))

        # Submit order
        order = await submit_order(
            user_id=state.user_id,
            items=items,
            total_usd=total,
            requires_approval=state.requires_approval,
        )

        state.order = order

        # Send confirmation notification
        if order["status"] == "submitted":
            msg = (
                f"Your order has been placed! "
                f"Order #{order['order_id']}: {items[0].get('name', 'item')} "
                f"(${total:.2f})"
            )
        else:
            msg = (
                f"Your order #{order['order_id']} is pending manager approval. "
                f"You'll be notified once it's approved."
            )

        notification = await send_notification(
            user_id=state.user_id,
            message=msg,
            notification_type="order_confirmation",
        )

        state.last_result = {
            "order": order,
            "notification": notification,
        }

        logger.info(
            "execution_agent_complete",
            trace_id=state.trace_id,
            order_id=order["order_id"],
            status=order["status"],
            total=total,
        )

        return state
