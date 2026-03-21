import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from plateful.db.models import Event, EventType


async def log_event(
    session: AsyncSession,
    *,
    user_id: str,
    session_id: str,
    event_type: EventType,
    payload: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> Event:
    event = Event(
        id=uuid.uuid4(),
        user_id=user_id,
        session_id=session_id,
        event_type=event_type,
        payload=payload or {},
        context=context or {},
    )
    session.add(event)
    await session.flush()
    return event


async def get_session_events(
    session: AsyncSession,
    *,
    user_id: str,
    session_id: str,
) -> list[Event]:
    stmt = (
        select(Event)
        .where(Event.user_id == user_id, Event.session_id == session_id)
        .order_by(Event.timestamp)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_user_events(
    session: AsyncSession,
    *,
    user_id: str,
    since: datetime | None = None,
    event_types: list[EventType] | None = None,
    limit: int = 100,
) -> list[Event]:
    stmt = select(Event).where(Event.user_id == user_id)
    if since:
        stmt = stmt.where(Event.timestamp >= since)
    if event_types:
        stmt = stmt.where(Event.event_type.in_(event_types))
    stmt = stmt.order_by(Event.timestamp.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
