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
