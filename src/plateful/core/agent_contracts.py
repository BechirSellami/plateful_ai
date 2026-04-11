"""Declarative agent contracts and a plan validator.

This module is the foundation for a DAG-based planner (future work) but is
shipped as a **zero-behavior-change** addition. It introduces:

1. ``AgentContract`` — a frozen dataclass describing each agent's logical
   inputs, outputs, and execution-ordering flags.
2. ``AGENT_CONTRACTS`` — the canonical contract registry for Plateful's
   agents. Contract names match the agent registry keys used by
   ``run_workflow``.
3. ``validate_plan`` — a pure function that checks an ordered plan
   (the same ``steps`` list that ``run_workflow`` already executes) against
   the contracts and returns a ``ValidationResult``. The validator never
   raises, so wiring it into the existing orchestrator cannot break an
   in-flight request.
4. ``state_to_initial_outputs`` — derives the set of logical outputs
   already present on a ``WorkflowState`` so validation naturally accounts
   for whatever the planner already extracted (e.g. ``selected_item``
   pulled out of a confirm_order message).

Used by:
  * ``run_workflow`` — validates each flow on entry in *warn mode*.
  * Future DAG planner — source of truth for dependency edges.

The contracts use *logical* output names rather than raw state field
names. For example, ``constraints`` is a logical output produced by the
planner/orchestrator; a contract that requires ``selected_item`` is
satisfied when ``state.constraints["selected_item"]`` is set, not when a
``state.selected_item`` attribute exists. This keeps contracts stable
even if the underlying state shape changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import structlog

if TYPE_CHECKING:
    from plateful.core.workflow import WorkflowState

logger = structlog.get_logger()


Severity = Literal["error", "warning", "info"]


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentContract:
    """Declarative contract for a workflow agent.

    Attributes:
        name: Registry name (matches the key in ``agent_registry``).
        requires: Logical outputs that MUST exist before the agent runs.
            Validation emits an ``error`` if any are missing.
        requires_any: Tuple of disjunctive groups. Each inner tuple is a
            "one-of" requirement — at least one element must already be
            produced. Used for agents like ``execution`` which accept
            several equivalent inputs (``selected_item`` OR
            ``recommendations`` OR ``meal_plan``).
        optional: Outputs the agent consumes as enrichment when available
            but does not depend on. Presence is not required and does not
            trigger validation errors.
        produces: Logical outputs the agent writes into ``WorkflowState``.
            Downstream agents can list these in ``requires`` /
            ``requires_any`` / ``optional``.
        post_action: If ``True``, the agent must run AFTER every
            non-post-action agent in the plan. Used for observer-style
            agents like ``learning`` which react to the outcome of the
            primary flow.
        side_effect: If ``True``, the agent mutates external systems
            (places an order, writes to memory). Consumed by audit logging
            and future safety checks.
    """

    name: str
    requires: tuple[str, ...] = ()
    requires_any: tuple[tuple[str, ...], ...] = ()
    optional: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    post_action: bool = False
    side_effect: bool = False


# Canonical logical outputs (documented here for reference only — not
# enforced at runtime). Keep this list in sync with contract definitions.
#
#   user_message        — the latest user turn. Always present at flow start.
#   intent              — produced by the planner / orchestrator understand step.
#   constraints         — produced by the planner / orchestrator understand step.
#   selected_item       — extracted when the user names a specific item.
#                         Lives on ``state.constraints["selected_item"]``.
#   preference          — extracted when the user states a preference.
#                         Lives on ``state.constraints["preference"]``.
#   user_profile        — produced by memory.
#   menu_items          — produced by menu.
#   recommendations     — produced by recommendation.
#   recommendation_text — produced by recommendation / mealplan / execution.
#   meal_plan           — produced by mealplan (may also already exist in session).
#   order               — produced by execution.
#   approval_decision   — produced by policy.
#   memory_write_result — produced by learning (side effect).

AGENT_CONTRACTS: dict[str, AgentContract] = {
    "orchestrator": AgentContract(
        name="orchestrator",
        requires=("user_message",),
        produces=("intent", "constraints"),
    ),
    "memory": AgentContract(
        name="memory",
        optional=("intent", "constraints"),
        produces=("user_profile",),
    ),
    "menu": AgentContract(
        name="menu",
        optional=("user_profile", "constraints"),
        produces=("menu_items",),
    ),
    "recommendation": AgentContract(
        name="recommendation",
        requires=("menu_items",),
        optional=("user_profile", "constraints"),
        produces=("recommendations", "recommendation_text"),
    ),
    "mealplan": AgentContract(
        name="mealplan",
        requires=("menu_items",),
        optional=("user_profile", "constraints", "meal_plan"),
        produces=("meal_plan", "recommendation_text"),
    ),
    "policy": AgentContract(
        name="policy",
        requires_any=(("recommendations", "menu_items"),),
        produces=("approval_decision",),
    ),
    "execution": AgentContract(
        name="execution",
        # Execution will order: an explicitly named item, the top
        # recommendation, the current meal_plan, or (as a last resort) the
        # first menu item. The contract captures all legitimate inputs.
        requires_any=(("selected_item", "recommendations", "meal_plan", "menu_items"),),
        optional=("approval_decision", "user_profile"),
        produces=("order", "recommendation_text"),
        side_effect=True,
    ),
    "learning": AgentContract(
        name="learning",
        optional=(
            "order",
            "recommendations",
            "meal_plan",
            "user_profile",
            "preference",
            "intent",
            "constraints",
        ),
        produces=("memory_write_result",),
        post_action=True,
        side_effect=True,
    ),
}


# Outputs always available at the start of any workflow, regardless of
# state. Anything tied to the user's request (e.g. ``user_message``) belongs
# here. State-derived outputs are handled by ``state_to_initial_outputs``.
ALWAYS_AVAILABLE: frozenset[str] = frozenset({"user_message"})


# ---------------------------------------------------------------------------
# Validation result types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidationIssue:
    """A single issue found while validating a plan."""

    severity: Severity
    code: str
    agent: str
    step: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "agent": self.agent,
            "step": self.step,
            "message": self.message,
        }


@dataclass
class ValidationResult:
    """Result of validating a plan against agent contracts."""

    issues: list[ValidationIssue] = field(default_factory=list)
    produced_outputs: set[str] = field(default_factory=set)

    @property
    def is_valid(self) -> bool:
        """True when no ``error``-severity issues were found."""
        return not any(i.severity == "error" for i in self.issues)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def summary(self) -> dict[str, Any]:
        """Compact structured summary — suitable for Langfuse span metadata."""
        return {
            "is_valid": self.is_valid,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [i.to_dict() for i in self.issues],
            "produced_outputs": sorted(self.produced_outputs),
        }

    def log(self, *, trace_id: str | None = None) -> None:
        """Emit each issue at the appropriate log level.

        The orchestrator calls this after validation so operators see
        inconsistencies in real time. Because the validator never raises,
        this is the only channel through which warnings surface today.
        """
        for issue in self.issues:
            if issue.severity == "error":
                log_fn: Any = logger.error
            elif issue.severity == "warning":
                log_fn = logger.warning
            else:
                log_fn = logger.info
            log_fn(
                "plan_validation_issue",
                trace_id=trace_id,
                **issue.to_dict(),
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def state_to_initial_outputs(state: WorkflowState) -> set[str]:
    """Derive the set of logical outputs already present on a state object.

    This lets the validator treat anything the planner or a previous turn
    already populated as "available", so flows that rely on extracted
    constraints (e.g. ``confirm_order`` needing ``selected_item``) validate
    cleanly when the extraction succeeded and surface an error only when
    it actually failed.
    """
    outputs: set[str] = set(ALWAYS_AVAILABLE)

    if state.intent:
        outputs.add("intent")
    if state.constraints:
        outputs.add("constraints")
        if state.constraints.get("selected_item"):
            outputs.add("selected_item")
        if state.constraints.get("preference"):
            outputs.add("preference")
    if state.user_profile:
        outputs.add("user_profile")
    if state.menu_items:
        outputs.add("menu_items")
    if state.recommendations:
        outputs.add("recommendations")
    if state.meal_plan:
        outputs.add("meal_plan")
    if state.order:
        outputs.add("order")
    if state.requires_approval or state.policy_result:
        outputs.add("approval_decision")

    return outputs


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_plan(
    steps: list[dict[str, Any]],
    *,
    contracts: dict[str, AgentContract] | None = None,
    initial_outputs: set[str] | frozenset[str] | None = None,
) -> ValidationResult:
    """Validate an ordered plan against declarative agent contracts.

    Args:
        steps: The same ``flow_def["steps"]`` list consumed by
            ``run_workflow``. Each element is a dict with at least an
            ``agent`` key and optionally a ``name`` key.
        contracts: Contract registry. Defaults to ``AGENT_CONTRACTS``.
        initial_outputs: Logical outputs already available at flow start
            (typically derived from ``WorkflowState`` via
            ``state_to_initial_outputs``). If ``None``, only
            ``ALWAYS_AVAILABLE`` is assumed.

    Checks performed:
        1. ``unknown_agent``: the plan references an agent with no contract.
           Severity = warning (the orchestrator already skips unknown
           agents with a warning of its own).
        2. ``missing_required_input``: a ``requires`` output is not in
           ``produced`` when the step runs. Severity = error.
        3. ``missing_required_any``: none of the alternatives in a
           ``requires_any`` group are in ``produced``. Severity = error.
        4. ``post_action_out_of_order``: a non-post-action agent runs
           after a post-action agent. Severity = warning.

    The validator never raises. Callers inspect ``is_valid`` /
    ``issues`` and decide how to react. ``run_workflow`` currently logs
    and continues — that's the "warn mode" contract of PR 1.
    """
    registry = contracts if contracts is not None else AGENT_CONTRACTS
    produced: set[str] = set(initial_outputs or ALWAYS_AVAILABLE)
    issues: list[ValidationIssue] = []

    # Track the earliest index at which we saw a post_action agent. Any
    # non-post-action agent that appears at or after this index is flagged.
    first_post_action_idx: int | None = None

    for idx, step in enumerate(steps):
        agent_name = str(step.get("agent", ""))
        step_name = str(step.get("name") or agent_name or f"step_{idx}")

        contract = registry.get(agent_name)
        if contract is None:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="unknown_agent",
                    agent=agent_name,
                    step=step_name,
                    message=(
                        f"No contract registered for agent '{agent_name}'. "
                        f"Skipping contract checks for this step."
                    ),
                )
            )
            continue

        # Rule 2 — required inputs must already be produced.
        for required_output in contract.requires:
            if required_output not in produced:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_required_input",
                        agent=agent_name,
                        step=step_name,
                        message=(
                            f"Agent '{agent_name}' requires '{required_output}' "
                            f"but no earlier step produces it. "
                            f"Produced so far: {sorted(produced)}"
                        ),
                    )
                )

        # Rule 3 — at least one option in each disjunctive group must exist.
        for group in contract.requires_any:
            if not any(option in produced for option in group):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="missing_required_any",
                        agent=agent_name,
                        step=step_name,
                        message=(
                            f"Agent '{agent_name}' requires one of "
                            f"{list(group)} but none are produced. "
                            f"Produced so far: {sorted(produced)}"
                        ),
                    )
                )

        # Rule 4 — post_action ordering.
        if contract.post_action:
            if first_post_action_idx is None:
                first_post_action_idx = idx
        elif first_post_action_idx is not None:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="post_action_out_of_order",
                    agent=agent_name,
                    step=step_name,
                    message=(
                        f"Non-post-action agent '{agent_name}' runs at "
                        f"index {idx}, after a post_action agent at "
                        f"index {first_post_action_idx}. post_action agents "
                        f"(e.g. learning) should run last."
                    ),
                )
            )

        # Record this agent's produced outputs for downstream checks.
        produced.update(contract.produces)

    return ValidationResult(issues=issues, produced_outputs=produced)
