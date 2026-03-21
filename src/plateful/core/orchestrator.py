import asyncio
from typing import Any

import structlog

from plateful.core.workflow import BaseAgent, WorkflowState

logger = structlog.get_logger()

# Background tasks must be stored to prevent garbage collection
_background_tasks: set[asyncio.Task[Any]] = set()

# Flow definition: declarative, data-driven workflow
CATERING_FLOW: dict[str, Any] = {
    "id": "catering_v1",
    "steps": [
        {"name": "understand", "agent": "orchestrator"},
        {"name": "enrich", "agent": "memory"},
        {"name": "retrieve", "agent": "menu", "post_check": "allergen_filter"},
        {"name": "recommend", "agent": "recommendation"},
        {"name": "validate", "agent": "policy"},
        {
            "name": "approve",
            "agent": "policy",
            "condition": "state.requires_approval == True",
        },
        {"name": "execute", "agent": "execution"},
        {"name": "learn", "agent": "learning", "async": True},
    ],
}

# Post-step safety checks (deterministic, non-negotiable)
SAFETY_CHECKS: dict[str, Any] = {}


def register_safety_check(name: str, check_fn: Any) -> None:
    SAFETY_CHECKS[name] = check_fn


def evaluate_condition(condition: str, state: WorkflowState) -> bool:
    """Evaluate a condition string against the workflow state.

    Only supports simple attribute comparisons for safety.
    """
    try:
        return bool(eval(condition, {"__builtins__": {}}, {"state": state}))
    except Exception:
        logger.warning("condition_evaluation_failed", condition=condition)
        return False


def run_safety_check(check_name: str, state: WorkflowState) -> None:
    """Run a deterministic safety check. Raises if violated."""
    check = SAFETY_CHECKS.get(check_name)
    if check:
        check(state)
    else:
        logger.warning("safety_check_not_found", check=check_name)


async def run_workflow(
    flow_def: dict[str, Any],
    state: WorkflowState,
    agent_registry: dict[str, BaseAgent],
    audit_fn: Any | None = None,
) -> WorkflowState:
    """Execute the workflow by iterating through steps and dispatching to agents."""
    for step in flow_def["steps"]:
        step_name = step["name"]
        agent_name = step["agent"]

        # Evaluate skip condition
        if "condition" in step and not evaluate_condition(step["condition"], state):
            logger.info("step_skipped", step=step_name, reason="condition_not_met")
            continue

        # Get agent
        agent = agent_registry.get(agent_name)
        if not agent:
            logger.warning("agent_not_found", agent=agent_name, step=step_name)
            continue

        logger.info("step_start", step=step_name, agent=agent_name, trace_id=state.trace_id)

        # Dispatch
        if step.get("async"):
            task = asyncio.create_task(agent.run(state))
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)
        else:
            state = await agent.run(state)

        # Post-step safety hooks
        if step.get("post_check"):
            run_safety_check(step["post_check"], state)

        # Audit
        if audit_fn:
            audit_fn(
                trace_id=state.trace_id,
                step=step_name,
                agent=agent_name,
                snapshot=state.snapshot(),
                output=state.last_result,
            )

        logger.info("step_complete", step=step_name, agent=agent_name, trace_id=state.trace_id)

    return state


def get_steps_from(flow_def: dict[str, Any], *, start_after: str) -> list[dict[str, Any]]:
    """Get remaining steps after a given step name (for resume after approval)."""
    steps: list[dict[str, Any]] = flow_def["steps"]
    for i, step in enumerate(steps):
        if step["name"] == start_after:
            return steps[i + 1 :]
    return []
