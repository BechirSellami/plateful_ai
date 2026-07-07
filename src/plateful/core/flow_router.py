"""Intent-based flow routing.

Instead of running every step for every message, the router selects
a flow based on the classified intent. The orchestrator runs in two
phases:

1. **Classify** — always run the ``understand`` step.
2. **Route** — look up ``state.intent`` in the flow map and execute
   only the steps that are relevant.

Unknown intents fall back to the default recommendation flow.
"""

from typing import Any

import structlog

logger = structlog.get_logger()

# Step templates (referenced by name in the flow map below).
# Each is a dict accepted by ``run_workflow``.
STEP_UNDERSTAND: dict[str, str] = {"name": "understand", "agent": "orchestrator"}
STEP_ENRICH: dict[str, str] = {"name": "enrich", "agent": "memory"}
STEP_RETRIEVE: dict[str, str] = {"name": "retrieve", "agent": "menu"}
STEP_RECOMMEND: dict[str, str] = {"name": "recommend", "agent": "recommendation"}
STEP_MEALPLAN: dict[str, str] = {"name": "mealplan", "agent": "mealplan"}
STEP_EXECUTE: dict[str, str] = {"name": "execute", "agent": "execution"}
STEP_LEARN: dict[str, str] = {"name": "learn", "agent": "learning"}


# Intent → post-classification steps (understand is always prepended)
INTENT_FLOWS: dict[str, list[dict[str, Any]]] = {
    "declare_preference": [
        STEP_LEARN,
    ],
    "order_meal": [
        STEP_ENRICH,
        STEP_RETRIEVE,
        STEP_RECOMMEND,
    ],
    "confirm_order": [
        # Enrich + retrieve run first so execution can resolve a
        # selected_item by name against a fresh menu and apply the user's
        # allergen profile. In stateful sessions (WebSocket) these steps
        # are idempotent — they overwrite any carried-forward menu_items
        # with the same day's menu.
        STEP_ENRICH,
        STEP_RETRIEVE,
        STEP_EXECUTE,
        STEP_LEARN,
    ],
    "get_recommendation": [
        STEP_ENRICH,
        STEP_RETRIEVE,
        STEP_RECOMMEND,
    ],
    "create_mealplan": [
        STEP_ENRICH,
        STEP_RETRIEVE,
        STEP_MEALPLAN,
    ],
    "submit_mealplan": [
        STEP_EXECUTE,
        STEP_LEARN,
    ],
    "check_order_status": [
        # Future: execution agent status lookup
    ],
    "ask_question": [
        STEP_ENRICH,
        STEP_RETRIEVE,
        STEP_RECOMMEND,
    ],
    "out_of_scope": [],
}

DEFAULT_FLOW: list[dict[str, Any]] = [
    STEP_ENRICH,
    STEP_RETRIEVE,
    STEP_RECOMMEND,
]


def get_flow_for_intent(
    intent: str | None,
    available_agents: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Return a complete flow definition for the given intent.

    Steps whose agent is not in *available_agents* are automatically
    dropped so the flow adapts to the configured environment (e.g. no
    ``memory`` step when Mem0 is not configured).

    The ``understand`` step is always first.
    """
    post_steps = INTENT_FLOWS.get(intent or "", DEFAULT_FLOW)

    # Filter out steps whose agent is not registered
    filtered = [s for s in post_steps if s["agent"] in available_agents]

    steps: list[dict[str, Any]] = [STEP_UNDERSTAND, *filtered]

    logger.info(
        "flow_routed",
        intent=intent,
        steps=[s["name"] for s in steps],
    )

    return {"steps": steps}


# Known compound flags. Kept as a list so callers can add / introspect new
# flags in one place. Flags are booleans on ``compound_flags``:
#
#   has_preference — the user expressed a food preference / allergy /
#                    dietary restriction alongside another intent.
#                    Appends ``learning`` when it isn't already in the flow.
#
# When adding a new flag, update this list, ``compose_plan`` below, and the
# PLANNER_SYSTEM_PROMPT so the LLM knows to emit it.
COMPOUND_FLAGS: tuple[str, ...] = ("has_preference",)


def compose_plan(
    intent: str | None,
    available_agents: set[str],
    *,
    compound_flags: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Compose the ordered list of post-classification agent steps.

    This is the single source of truth for plan composition. Both the
    LLM planner and the keyword fallback call into it so the two paths
    stay synchronised. The ``understand`` step is stripped because by
    the time we compose the plan, classification has already happened.

    Args:
        intent: Classified intent. Unknown intents fall back to
            ``DEFAULT_FLOW`` via ``get_flow_for_intent``.
        available_agents: Registry keys that currently exist. Steps for
            unavailable agents are skipped.
        compound_flags: Boolean flags that extend the base flow. See
            ``COMPOUND_FLAGS`` for the supported keys.

    Returns:
        A list of ``{"agent": str, "reason": str}`` dicts — the shape
        consumed by ``run_planned_workflow``.
    """
    flags = compound_flags or {}

    flow = get_flow_for_intent(intent, available_agents)
    # The planner already did ``understand`` — drop it so we don't run
    # the orchestrator's intent classifier a second time.
    post_steps = [s for s in flow["steps"] if s["name"] != "understand"]

    plan: list[dict[str, Any]] = [
        {"agent": s["agent"], "reason": f"Flow step: {s['name']}"} for s in post_steps
    ]

    # has_preference — append learning when the user stated a preference
    # alongside a non-preference intent, learning is available, and the
    # base flow doesn't already end with it.
    if (
        flags.get("has_preference")
        and intent != "declare_preference"
        and "learning" in available_agents
        and not any(s["agent"] == "learning" for s in plan)
    ):
        plan.append({"agent": "learning", "reason": "Persist user preference"})

    return plan
