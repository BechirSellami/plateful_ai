from unittest.mock import AsyncMock, MagicMock

import pytest

from plateful.db.event_store import get_session_events, get_user_events, log_event
from plateful.db.models import EventType


@pytest.mark.unit
class TestLogEvent:
    async def test_creates_event_with_required_fields(self) -> None:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()

        event = await log_event(
            mock_session,
            user_id="emp_123",
            session_id="sess_abc",
            event_type=EventType.ORDER_PLACED,
        )

        assert event.user_id == "emp_123"
        assert event.session_id == "sess_abc"
        assert event.event_type == EventType.ORDER_PLACED
        assert event.payload == {}
        assert event.context == {}
        mock_session.add.assert_called_once_with(event)
        mock_session.flush.assert_awaited_once()

    async def test_creates_event_with_payload_and_context(self) -> None:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        payload = {"item_id": "bowl_42", "quantity": 2}
        context = {"meal_type": "lunch", "day_of_week": "monday"}

        event = await log_event(
            mock_session,
            user_id="emp_456",
            session_id="sess_def",
            event_type=EventType.ITEM_ADDED,
            payload=payload,
            context=context,
        )

        assert event.payload == payload
        assert event.context == context

    async def test_generates_unique_ids(self) -> None:
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        event1 = await log_event(
            mock_session,
            user_id="emp_123",
            session_id="sess_abc",
            event_type=EventType.ORDER_PLACED,
        )
        event2 = await log_event(
            mock_session,
            user_id="emp_123",
            session_id="sess_abc",
            event_type=EventType.ORDER_PLACED,
        )
        assert event1.id != event2.id


@pytest.mark.unit
class TestGetSessionEvents:
    async def test_queries_by_user_and_session(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await get_session_events(mock_session, user_id="emp_123", session_id="sess_abc")

        assert result == []
        mock_session.execute.assert_awaited_once()


@pytest.mark.unit
class TestGetUserEvents:
    async def test_queries_by_user_id(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await get_user_events(mock_session, user_id="emp_123")

        assert result == []
        mock_session.execute.assert_awaited_once()

    async def test_filters_by_event_types(self) -> None:
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute.return_value = mock_result

        result = await get_user_events(
            mock_session,
            user_id="emp_123",
            event_types=[EventType.ORDER_PLACED, EventType.ITEM_ADDED],
        )

        assert result == []
