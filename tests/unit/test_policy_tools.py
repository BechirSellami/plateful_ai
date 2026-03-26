import pytest

from plateful.tools.policy_tools import PolicyViolation, validate_order

STRICT_POLICIES = [
    {
        "id": "p1",
        "department_id": "engineering",
        "rule_type": "budget_cap",
        "params": {"max_usd": 50.0},
        "active": True,
    },
    {
        "id": "p2",
        "department_id": "engineering",
        "rule_type": "per_person_limit",
        "params": {"max_usd": 25.0},
        "active": True,
    },
    {
        "id": "p3",
        "department_id": "engineering",
        "rule_type": "approval_threshold",
        "params": {"requires_approval_above": 30.0},
        "active": True,
    },
]


@pytest.mark.unit
class TestValidateOrder:
    def test_order_within_budget_passes(self) -> None:
        result = validate_order(20.0, policies=STRICT_POLICIES, department_id="engineering")
        assert result["passed"] is True
        assert result["violations"] == []

    def test_order_exceeding_budget_fails(self) -> None:
        result = validate_order(60.0, policies=STRICT_POLICIES, department_id="engineering")
        assert result["passed"] is False
        violations = result["violations"]
        assert any(v["rule_type"] == "budget_cap" for v in violations)

    def test_approval_required_above_threshold(self) -> None:
        # Use only the approval threshold policy to test in isolation
        approval_only = [
            {
                "id": "p3",
                "department_id": "default",
                "rule_type": "approval_threshold",
                "params": {"requires_approval_above": 30.0},
                "active": True,
            },
        ]
        result = validate_order(35.0, policies=approval_only)
        assert result["requires_approval"] is True
        assert result["passed"] is True  # not blocked, just needs approval

    def test_no_approval_below_threshold(self) -> None:
        result = validate_order(20.0, policies=STRICT_POLICIES, department_id="engineering")
        assert result["requires_approval"] is False

    def test_per_person_limit_enforced(self) -> None:
        # 1 person ordering $30 exceeds $25 per-person limit
        result = validate_order(
            30.0, item_count=1, policies=STRICT_POLICIES, department_id="engineering"
        )
        violations = result["violations"]
        assert any(v["rule_type"] == "per_person_limit" for v in violations)

    def test_per_person_limit_passes_with_multiple(self) -> None:
        # 2 people splitting $40 = $20/person, under $25 limit
        result = validate_order(
            40.0, item_count=2, policies=STRICT_POLICIES, department_id="engineering"
        )
        per_person_violations = [
            v for v in result["violations"] if v["rule_type"] == "per_person_limit"
        ]
        assert per_person_violations == []

    def test_falls_back_to_default_policies(self) -> None:
        result = validate_order(20.0, department_id="unknown_dept")
        assert result["passed"] is True  # uses default policies

    def test_inactive_policies_ignored(self) -> None:
        policies = [
            {
                "id": "p1",
                "department_id": "default",
                "rule_type": "budget_cap",
                "params": {"max_usd": 10.0},
                "active": False,  # inactive
            },
        ]
        result = validate_order(50.0, policies=policies)
        # No active policies matching, falls back to empty check
        assert result["passed"] is True

    def test_returns_order_total(self) -> None:
        result = validate_order(42.50)
        assert result["order_total"] == 42.50

    def test_zero_total_passes(self) -> None:
        result = validate_order(0.0)
        assert result["passed"] is True


@pytest.mark.unit
class TestPolicyViolation:
    def test_to_dict(self) -> None:
        v = PolicyViolation("budget_cap", "Over budget", blocking=True)
        d = v.to_dict()
        assert d["rule_type"] == "budget_cap"
        assert d["message"] == "Over budget"
        assert d["blocking"] is True

    def test_non_blocking_violation(self) -> None:
        v = PolicyViolation("warning", "Approaching limit", blocking=False)
        assert v.blocking is False
