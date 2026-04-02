import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class WorkflowState:
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    session_id: str = ""
    intent: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    user_profile: dict[str, Any] = field(default_factory=dict)
    menu_items: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    recommendation_text: str | None = None
    policy_result: dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False
    order: dict[str, Any] | None = None
    last_result: Any = None
    messages: list[dict[str, str]] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "intent": self.intent,
            "constraints": self.constraints,
            "menu_items_count": len(self.menu_items),
            "recommendations_count": len(self.recommendations),
            "requires_approval": self.requires_approval,
            "has_order": self.order is not None,
        }


class BaseAgent(Protocol):
    async def run(self, state: WorkflowState) -> WorkflowState: ...
