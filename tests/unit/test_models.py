import uuid
from decimal import Decimal

import pytest

from plateful.db.models import (
    ApprovalStatus,
    AuditOutcome,
    AuditTrail,
    DecisionType,
    Event,
    EventType,
    MenuItem,
    Order,
    OrderStatus,
    Policy,
    PolicyRuleType,
)


@pytest.mark.unit
class TestEventModel:
    def test_event_type_values(self) -> None:
        assert EventType.ORDER_PLACED == "order_placed"
        assert EventType.ALLERGY_DECLARED == "allergy_declared"

    def test_event_instantiation(self) -> None:
        event = Event(
            id=uuid.uuid4(),
            user_id="emp_123",
            session_id="sess_abc",
            event_type=EventType.ORDER_PLACED,
            payload={"item_id": "bowl_42"},
            context={"meal_type": "lunch"},
        )
        assert event.user_id == "emp_123"
        assert event.event_type == EventType.ORDER_PLACED
        assert event.payload["item_id"] == "bowl_42"


@pytest.mark.unit
class TestMenuItemModel:
    def test_menu_item_instantiation(self) -> None:
        item = MenuItem(
            id=uuid.uuid4(),
            name="Grilled Chicken Bowl",
            description="A healthy bowl",
            price_usd=Decimal("18.50"),
            category="healthy",
            cuisine="thai",
            calories=450,
            active=True,
        )
        assert item.name == "Grilled Chicken Bowl"
        assert item.price_usd == Decimal("18.50")
        assert item.active is True


@pytest.mark.unit
class TestOrderModel:
    def test_order_status_values(self) -> None:
        assert OrderStatus.PENDING == "pending"
        assert OrderStatus.DELIVERED == "delivered"

    def test_approval_status_values(self) -> None:
        assert ApprovalStatus.NOT_REQUIRED == "not_required"
        assert ApprovalStatus.APPROVED == "approved"

    def test_order_instantiation(self) -> None:
        order = Order(
            id=uuid.uuid4(),
            user_id="emp_123",
            status=OrderStatus.PENDING,
            total_usd=Decimal("25.00"),
            approval_status=ApprovalStatus.NOT_REQUIRED,
        )
        assert order.status == OrderStatus.PENDING
        assert order.total_usd == Decimal("25.00")


@pytest.mark.unit
class TestPolicyModel:
    def test_policy_rule_types(self) -> None:
        assert PolicyRuleType.BUDGET_CAP == "budget_cap"
        assert PolicyRuleType.APPROVAL_THRESHOLD == "approval_threshold"

    def test_policy_instantiation(self) -> None:
        policy = Policy(
            id=uuid.uuid4(),
            department_id="engineering",
            rule_type=PolicyRuleType.BUDGET_CAP,
            params={"max_usd": 25},
            active=True,
        )
        assert policy.params["max_usd"] == 25


@pytest.mark.unit
class TestAuditTrailModel:
    def test_decision_types(self) -> None:
        assert DecisionType.RECOMMENDATION == "recommendation"
        assert DecisionType.ALLERGY_FILTER == "allergy_filter"

    def test_audit_outcome_values(self) -> None:
        assert AuditOutcome.ACCEPTED == "accepted"
        assert AuditOutcome.REJECTED == "rejected"

    def test_audit_trail_instantiation(self) -> None:
        audit = AuditTrail(
            id=uuid.uuid4(),
            trace_id=uuid.uuid4(),
            user_id="emp_123",
            decision_type=DecisionType.POLICY_CHECK,
            agent="policy",
            input_snapshot={"order_total": 30},
            output_snapshot={"passed": True},
            outcome=AuditOutcome.ACCEPTED,
        )
        assert audit.agent == "policy"
        assert audit.outcome == AuditOutcome.ACCEPTED
