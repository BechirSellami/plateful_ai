"""Execution Agent: submits orders and sends confirmations.

Completes the happy path by placing the order and notifying the user.
If the policy agent flagged requires_approval, the order is placed in
pending_approval status instead of submitted.
"""

from typing import Any

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

        # Resolve the item to order
        items = self._resolve_order_items(state)
        if not items:
            state.last_result = {"status": "error", "reason": "No items to order"}
            return state

        total = sum(float(item.get("price_usd", 0)) for item in items)

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

    def _resolve_order_items(self, state: WorkflowState) -> list[dict[str, Any]]:
        """Determine which item(s) to order.

        Resolution order:
        1. If ``selected_item`` is in constraints, match it against menu_items.
        2. Otherwise fall back to the top recommendation, then first menu item.
        """
        selected = state.constraints.get("selected_item", "")
        search_pool = state.menu_items or []

        if selected:
            selected_lower = selected.lower()
            for item in search_pool:
                if selected_lower in item.get("name", "").lower():
                    return [item]
            # Fuzzy: check if any word from selected matches an item name
            selected_words = {w for w in selected_lower.split() if len(w) > 2}
            for item in search_pool:
                item_lower = item.get("name", "").lower()
                if any(w in item_lower for w in selected_words):
                    return [item]

        # Fallback: top recommendation or first menu item
        if state.recommendations:
            return state.recommendations[:1]
        if search_pool:
            return search_pool[:1]
        return []
