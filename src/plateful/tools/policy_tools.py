"""Tools for the Policy Agent to validate orders against department rules."""

from typing import Any

# Default policies used when no DB is available (local testing)
DEFAULT_POLICIES: list[dict[str, Any]] = [
    {
        "id": "pol_1",
        "department_id": "default",
        "rule_type": "budget_cap",
        "params": {"max_usd": 50.0},
        "active": True,
    },
    {
        "id": "pol_2",
        "department_id": "default",
        "rule_type": "per_person_limit",
        "params": {"max_usd": 30.0},
        "active": True,
    },
    {
        "id": "pol_3",
        "department_id": "default",
        "rule_type": "approval_threshold",
        "params": {"requires_approval_above": 25.0},
        "active": True,
    },
]


class PolicyViolation:
    """Represents a policy rule violation."""

    def __init__(self, rule_type: str, message: str, *, blocking: bool = True) -> None:
        self.rule_type = rule_type
        self.message = message
        self.blocking = blocking

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_type": self.rule_type,
            "message": self.message,
            "blocking": self.blocking,
        }


def validate_order(
    order_total: float,
    item_count: int = 1,
    department_id: str = "default",
    policies: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate an order against department policy rules.

    Returns a result dict with:
    - passed: bool
    - requires_approval: bool
    - violations: list of policy violations
    """
    active_policies = policies or DEFAULT_POLICIES
    dept_policies = [
        p for p in active_policies if p.get("department_id") == department_id and p.get("active")
    ]

    # Fall back to default if no dept-specific policies
    if not dept_policies:
        dept_policies = [
            p for p in active_policies if p.get("department_id") == "default" and p.get("active")
        ]

    violations: list[PolicyViolation] = []
    requires_approval = False

    for policy in dept_policies:
        rule_type = policy.get("rule_type", "")
        params = policy.get("params", {})

        if rule_type == "budget_cap":
            max_usd = params.get("max_usd", float("inf"))
            if order_total > max_usd:
                violations.append(
                    PolicyViolation(
                        rule_type="budget_cap",
                        message=f"Order total ${order_total:.2f} exceeds budget cap ${max_usd:.2f}",
                        blocking=True,
                    )
                )

        elif rule_type == "per_person_limit":
            max_per_person = params.get("max_usd", float("inf"))
            per_person = order_total / max(item_count, 1)
            if per_person > max_per_person:
                violations.append(
                    PolicyViolation(
                        rule_type="per_person_limit",
                        message=f"Per-person cost ${per_person:.2f} exceeds limit ${max_per_person:.2f}",
                        blocking=True,
                    )
                )

        elif rule_type == "approval_threshold":
            threshold = params.get("requires_approval_above", float("inf"))
            if order_total > threshold:
                requires_approval = True

    blocking_violations = [v for v in violations if v.blocking]

    return {
        "passed": len(blocking_violations) == 0,
        "requires_approval": requires_approval,
        "violations": [v.to_dict() for v in violations],
        "order_total": order_total,
    }
