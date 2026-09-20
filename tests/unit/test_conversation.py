"""Unit tests for the conversation transcript helpers."""

import pytest

from plateful.core.conversation import (
    ERROR_ASSISTANT_TURN,
    bounded_history,
    render_assistant_turn,
)
from plateful.core.workflow import WorkflowState


@pytest.mark.unit
class TestBoundedHistory:
    def test_passes_through_alternating_history(self) -> None:
        msgs = [
            {"role": "user", "content": "what's good?"},
            {"role": "assistant", "content": "1. Pad Thai\n2. Chicken Katsu"},
            {"role": "user", "content": "the second one"},
        ]
        assert bounded_history(msgs) == msgs

    def test_missing_role_defaults_to_user(self) -> None:
        assert bounded_history([{"content": "hi"}]) == [{"role": "user", "content": "hi"}]

    def test_trims_to_most_recent_limit(self) -> None:
        msgs = []
        for i in range(30):
            role = "user" if i % 2 == 0 else "assistant"
            msgs.append({"role": role, "content": f"m{i}"})
        # 30 messages ends on assistant; add the current user turn.
        msgs.append({"role": "user", "content": "now"})

        out = bounded_history(msgs, limit=6)

        # The raw window of 6 starts on an assistant turn, which is dropped
        # so the history starts with a user turn as the API requires.
        assert len(out) == 5
        assert [m["content"] for m in out] == ["m26", "m27", "m28", "m29", "now"]
        assert out[0]["role"] == "user"
        assert out[-1] == {"role": "user", "content": "now"}

    def test_window_never_starts_with_assistant(self) -> None:
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
            {"role": "user", "content": "c"},
        ]
        out = bounded_history(msgs, limit=2)
        assert out == [{"role": "user", "content": "c"}]

    def test_drops_trailing_assistant_turn(self) -> None:
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]
        assert bounded_history(msgs) == [{"role": "user", "content": "a"}]

    def test_merges_adjacent_same_role_turns(self) -> None:
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "user", "content": "b"},
        ]
        assert bounded_history(msgs) == [{"role": "user", "content": "a\n\nb"}]

    def test_skips_blank_messages(self) -> None:
        msgs = [
            {"role": "user", "content": "a"},
            {"role": "assistant", "content": "   "},
            {"role": "user", "content": "b"},
        ]
        assert bounded_history(msgs) == [{"role": "user", "content": "a\n\nb"}]

    def test_empty_input(self) -> None:
        assert bounded_history([]) == []


@pytest.mark.unit
class TestRenderAssistantTurn:
    def test_prefers_recommendation_text(self) -> None:
        state = WorkflowState(
            recommendation_text="Here are my top picks:\n1. Pad Thai",
            order={"order_id": "ord_1", "items": [], "total_usd": 0},
        )
        assert render_assistant_turn(state) == "Here are my top picks:\n1. Pad Thai"

    def test_renders_submitted_order(self) -> None:
        state = WorkflowState(
            order={
                "order_id": "ord_abc",
                "status": "submitted",
                "items": [{"name": "Chicken Katsu", "price_usd": 12.5}],
                "total_usd": 12.5,
            }
        )
        out = render_assistant_turn(state)
        assert "ord_abc" in out
        assert "Chicken Katsu" in out
        assert "$12.50" in out

    def test_renders_pending_approval_order(self) -> None:
        state = WorkflowState(
            order={
                "order_id": "ord_p",
                "status": "pending_approval",
                "items": [{"name": "Lobster Roll", "price_usd": 40}],
                "total_usd": 40,
            }
        )
        assert "pending manager approval" in render_assistant_turn(state)

    def test_renders_ingredient_allergen_conflict(self) -> None:
        state = WorkflowState(
            allergen_conflicts=[
                {
                    "ingredient": "shrimp",
                    "allergen_group": "shellfish",
                    "items_removed": ["Pad Thai"],
                    "matched_allergens": ["shellfish"],
                }
            ]
        )
        out = render_assistant_turn(state)
        assert "shrimp" in out
        assert "shellfish" in out

    def test_renders_item_allergen_conflict(self) -> None:
        state = WorkflowState(
            allergen_conflicts=[{"name": "Pad Thai", "matched_allergens": ["peanuts"]}]
        )
        out = render_assistant_turn(state)
        assert "Pad Thai" in out
        assert "peanuts" in out

    def test_never_empty(self) -> None:
        assert render_assistant_turn(WorkflowState()).strip()

    def test_error_turn_is_non_empty(self) -> None:
        assert ERROR_ASSISTANT_TURN.strip()
