import asyncio
import inspect
from typing import Any

import structlog

from plateful.core.flow_router import get_flow_for_intent
from plateful.core.observability import TracingContext, trace_agent_step
from plateful.core.workflow import BaseAgent, WorkflowState

logger = structlog.get_logger()

# Background tasks must be stored to prevent garbage collection
_background_tasks: set[asyncio.Task[Any]] = set()


# ---------------------------------------------------------------------------
# Per-agent I/O snapshots for Langfuse span visibility
# ---------------------------------------------------------------------------


def _agent_input(agent_name: str, state: WorkflowState) -> dict[str, Any]:
    """Capture the relevant state fields an agent reads as its input."""
    base: dict[str, Any] = {
        "user_id": state.user_id,
        "intent": state.intent,
    }
    if state.messages:
        base["user_message"] = state.messages[-1].get("content", "")

    if agent_name == "memory":
        base["constraints"] = state.constraints
    elif agent_name == "menu":
        base["constraints"] = state.constraints
        base["allergies"] = state.user_profile.get("allergies", [])
    elif agent_name in ("recommendation", "mealplan"):
        base["menu_items_count"] = len(state.menu_items)
        base["constraints"] = state.constraints
        base["user_profile"] = state.user_profile
    elif agent_name == "execution":
        base["recommendations_count"] = len(state.recommendations)
        base["requires_approval"] = state.requires_approval
        meal_plan = getattr(state, "meal_plan", None)
        if meal_plan:
            base["meal_plan_days"] = list(meal_plan.keys())
    elif agent_name == "learning":
        base["last_result_type"] = type(state.last_result).__name__

    return base


def _agent_output(agent_name: str, state: WorkflowState) -> dict[str, Any]:
    """Capture what the agent produced after running."""
    if agent_name == "memory":
        return {
            "user_profile": state.user_profile,
        }
    elif agent_name == "menu":
        return {
            "menu_items_count": len(state.menu_items),
            "menu_items": [
                {"name": i.get("name"), "price_usd": i.get("price_usd")}
                for i in state.menu_items[:10]  # cap for readability
            ],
        }
    elif agent_name == "recommendation":
        return {
            "recommendations": [
                {"name": r.get("name"), "score": r.get("score")} for r in state.recommendations
            ],
            "recommendation_text": (state.recommendation_text or "")[:500],
        }
    elif agent_name == "mealplan":
        meal_plan = getattr(state, "meal_plan", {})
        return {
            "meal_plan": {day: entry.get("name", "") for day, entry in meal_plan.items()},
            "recommendation_text": (state.recommendation_text or "")[:500],
        }
    elif agent_name == "execution":
        return {
            "order": state.order,
        }
    elif agent_name == "learning":
        return {
            "last_result": str(state.last_result)[:300] if state.last_result else None,
        }

    # Fallback: generic snapshot
    return {"last_result": str(state.last_result)[:300] if state.last_result else None}


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

        # Dispatch with observability span — attach I/O for Langfuse visibility
        tracing: TracingContext | None = getattr(state, "_tracing", None)
        input_snap = _agent_input(agent_name, state)
        with trace_agent_step(tracing, agent_name=agent_name, step_name=step_name) as span:
            if step.get("async"):
                task = asyncio.create_task(agent.run(state))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            else:
                state = await agent.run(state)
            span.update(input=input_snap, output=_agent_output(agent_name, state))

        # Post-step safety hooks
        if step.get("post_check"):
            run_safety_check(step["post_check"], state)

        # Audit (supports both sync and async callbacks)
        if audit_fn:
            result = audit_fn(
                trace_id=state.trace_id,
                step=step_name,
                agent=agent_name,
                snapshot=state.snapshot(),
                output=state.last_result,
            )
            if inspect.isawaitable(result):
                await result

        logger.info("step_complete", step=step_name, agent=agent_name, trace_id=state.trace_id)

    return state


async def run_adaptive_workflow(
    state: WorkflowState,
    agent_registry: dict[str, BaseAgent],
    audit_fn: Any | None = None,
) -> WorkflowState:
    """Two-phase workflow: classify intent first, then route to the right flow.

    Phase 1 — run the ``understand`` step to classify intent.
    Phase 2 — select and execute the remaining steps based on ``state.intent``.
    """
    # Phase 1: classify intent
    intent_agent = agent_registry.get("orchestrator")
    if intent_agent:
        logger.info("step_start", step="understand", agent="orchestrator", trace_id=state.trace_id)
        state = await intent_agent.run(state)
        logger.info(
            "step_complete", step="understand", agent="orchestrator", trace_id=state.trace_id
        )

    # Phase 2: route based on intent
    available = set(agent_registry.keys())
    flow = get_flow_for_intent(state.intent, available)

    # Skip the understand step (already executed in phase 1)
    remaining_steps = [s for s in flow["steps"] if s["name"] != "understand"]
    remaining_flow = {"steps": remaining_steps}

    state = await run_workflow(remaining_flow, state, agent_registry, audit_fn=audit_fn)

    return state


async def run_planned_workflow(
    state: WorkflowState,
    agent_registry: dict[str, BaseAgent],
    planner: Any,
    audit_fn: Any | None = None,
) -> WorkflowState:
    """Planner-driven workflow: LLM builds an execution plan, then we run it.

    Phase 1 — Planner analyzes the user message and produces an ordered list
    of agent steps (handles compound intents like preference + order).
    Phase 2 — Execute each step in the plan sequentially.
    """
    # Create observability trace for this request
    tracing = TracingContext.create(
        trace_id=state.trace_id,
        user_id=state.user_id,
        session_id=state.session_id,
    )
    state._tracing = tracing  # type: ignore[attr-defined]

    try:
        # Phase 1: plan (traced as a span)
        with trace_agent_step(tracing, agent_name="planner", step_name="plan") as plan_span:
            available = {k for k in agent_registry if k != "orchestrator"}
            plan_result = await planner.plan(state, available)
            plan_span.update(
                input={
                    "user_message": state.messages[-1].get("content", "") if state.messages else ""
                },
                output={
                    "intent": plan_result.get("intent"),
                    "constraints": plan_result.get("constraints", {}),
                    "plan": [s.get("agent") for s in plan_result.get("plan", [])],
                },
            )

        # Phase 2: execute the plan
        plan_steps = plan_result.get("plan", [])
        flow_steps = [
            {"name": step.get("reason", step["agent"]), "agent": step["agent"]}
            for step in plan_steps
        ]
        flow_def: dict[str, Any] = {"steps": flow_steps}

        state = await run_workflow(flow_def, state, agent_registry, audit_fn=audit_fn)
    finally:
        tracing.flush()

    return state


def get_steps_from(flow_def: dict[str, Any], *, start_after: str) -> list[dict[str, Any]]:
    """Get remaining steps after a given step name (for resume after approval)."""
    steps: list[dict[str, Any]] = flow_def["steps"]
    for i, step in enumerate(steps):
        if step["name"] == start_after:
            return steps[i + 1 :]
    return []
