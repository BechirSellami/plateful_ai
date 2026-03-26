import pytest

from plateful.tools.learning_tools import build_mem0_messages, summarize_session_events


@pytest.mark.unit
class TestSummarizeSessionEvents:
    def test_empty_events_returns_empty(self) -> None:
        assert summarize_session_events([]) == ""

    def test_order_placed(self) -> None:
        events = [
            {"event_type": "order_placed", "payload": {"item_name": "Chicken Bowl", "price_usd": 18.5}}
        ]
        result = summarize_session_events(events)
        assert "Chicken Bowl" in result
        assert "$18.5" in result

    def test_order_placed_no_price(self) -> None:
        events = [{"event_type": "order_placed", "payload": {"item_name": "Salad"}}]
        result = summarize_session_events(events)
        assert "Salad" in result
        assert "$" not in result

    def test_item_added(self) -> None:
        events = [{"event_type": "item_added", "payload": {"item_name": "Fries"}}]
        assert "added Fries" in summarize_session_events(events)

    def test_item_removed(self) -> None:
        events = [{"event_type": "item_removed", "payload": {"item_name": "Soda"}}]
        assert "removed Soda" in summarize_session_events(events)

    def test_item_swapped(self) -> None:
        events = [
            {"event_type": "item_swapped", "payload": {"old_item": "Beef", "new_item": "Tofu"}}
        ]
        result = summarize_session_events(events)
        assert "Beef" in result
        assert "Tofu" in result

    def test_suggestion_accepted(self) -> None:
        events = [{"event_type": "suggestion_accepted", "payload": {"item_name": "Pasta"}}]
        assert "accepted suggestion: Pasta" in summarize_session_events(events)

    def test_suggestion_rejected(self) -> None:
        events = [{"event_type": "suggestion_rejected", "payload": {"item_name": "Sushi"}}]
        assert "rejected suggestion: Sushi" in summarize_session_events(events)

    def test_rating_given(self) -> None:
        events = [
            {"event_type": "rating_given", "payload": {"item_name": "Pizza", "rating": 4}}
        ]
        result = summarize_session_events(events)
        assert "Pizza" in result
        assert "4/5" in result

    def test_allergy_declared(self) -> None:
        events = [{"event_type": "allergy_declared", "payload": {"ingredient": "peanuts"}}]
        assert "allergy to peanuts" in summarize_session_events(events)

    def test_mealplan_edited(self) -> None:
        events = [{"event_type": "mealplan_edited", "payload": {"day": "Monday"}}]
        assert "Monday" in summarize_session_events(events)

    def test_multiple_events_joined(self) -> None:
        events = [
            {"event_type": "item_added", "payload": {"item_name": "A"}},
            {"event_type": "item_added", "payload": {"item_name": "B"}},
        ]
        result = summarize_session_events(events)
        assert ". " in result
        assert "A" in result
        assert "B" in result

    def test_unknown_event_type_ignored(self) -> None:
        events = [{"event_type": "unknown_thing", "payload": {}}]
        assert summarize_session_events(events) == ""

    def test_missing_payload_uses_defaults(self) -> None:
        events = [{"event_type": "order_placed", "payload": {}}]
        result = summarize_session_events(events)
        assert "an item" in result


@pytest.mark.unit
class TestBuildMem0Messages:
    def test_empty_summary_returns_empty(self) -> None:
        assert build_mem0_messages("") == []

    def test_wraps_summary_in_message(self) -> None:
        messages = build_mem0_messages("User ordered Chicken Bowl")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        assert "Chicken Bowl" in messages[0]["content"]
        assert "food preferences" in messages[0]["content"]
