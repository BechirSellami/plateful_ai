"""Tools for the Execution Agent to submit orders and send notifications."""

import uuid
from datetime import UTC, datetime
from typing import Any


async def submit_order(
    *,
    user_id: str,
    items: list[dict[str, Any]],
    total_usd: float,
    delivery_time: str | None = None,
    requires_approval: bool = False,
) -> dict[str, Any]:
    """Submit an order. Returns order confirmation.

    In production, this would write to the orders table and call vendor APIs.
    For now, returns a simulated order confirmation.
    """
    order_id = f"ord_{uuid.uuid4().hex[:8]}"
    status = "pending_approval" if requires_approval else "submitted"

    return {
        "order_id": order_id,
        "user_id": user_id,
        "status": status,
        "items": [
            {"name": item.get("name", "Unknown"), "price_usd": item.get("price_usd", 0)}
            for item in items
        ],
        "total_usd": total_usd,
        "delivery_time": delivery_time,
        "created_at": datetime.now(UTC).isoformat(),
    }


async def send_notification(
    *,
    user_id: str,
    message: str,
    notification_type: str = "order_confirmation",
) -> dict[str, Any]:
    """Send a notification to the user.

    In production, this would send via WebSocket, email, or push notification.
    For now, returns the notification payload.
    """
    return {
        "notification_id": f"notif_{uuid.uuid4().hex[:8]}",
        "user_id": user_id,
        "type": notification_type,
        "message": message,
        "sent_at": datetime.now(UTC).isoformat(),
    }
