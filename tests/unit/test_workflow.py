import pytest

from plateful.core.workflow import WorkflowState


@pytest.mark.unit
class TestWorkflowState:
    def test_defaults(self) -> None:
        state = WorkflowState(user_id="emp_123", session_id="sess_abc")
        assert state.user_id == "emp_123"
        assert state.intent is None
        assert state.constraints == {}
        assert state.user_profile == {}
        assert state.menu_items == []
        assert state.requires_approval is False
        assert state.order is None

    def test_snapshot_returns_summary(self) -> None:
        state = WorkflowState(
            user_id="emp_123",
            session_id="sess_abc",
            intent="order_lunch",
            menu_items=[{"id": "1"}, {"id": "2"}],
            requires_approval=True,
        )
        snap = state.snapshot()
        assert snap["user_id"] == "emp_123"
        assert snap["intent"] == "order_lunch"
        assert snap["menu_items_count"] == 2
        assert snap["requires_approval"] is True
        assert snap["has_order"] is False

    def test_trace_id_auto_generated(self) -> None:
        s1 = WorkflowState(user_id="a", session_id="b")
        s2 = WorkflowState(user_id="a", session_id="b")
        assert s1.trace_id != s2.trace_id
