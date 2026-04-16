"""Planner Agent: builds an execution plan from a user message.

Replaces the single-intent classification + static flow routing with an
LLM-driven planner that can handle compound requests like
"I love tofu. I'll have it today" → [learn preference, execute order].

Falls back to keyword-based intent classification when no LLM is available.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Literal

import anthropic
import structlog

from plateful.core.workflow import WorkflowState

logger = structlog.get_logger()

# Agent descriptions that the planner uses to build execution plans.
# Keys must match the agent registry names.
AGENT_CATALOG: dict[str, str] = {
    "memory": (
        "Retrieves user preferences, allergies, and order history from memory. "
        "Use when you need to personalise recommendations or check dietary restrictions."
    ),
    "menu": (
        "Fetches and filters today's menu items, applying allergen safety filters. "
        "Use before making recommendations or when the user asks about available options."
    ),
    "recommendation": (
        "Ranks menu items and generates personalised meal suggestions. "
        "Use after menu retrieval when the user wants suggestions or is deciding what to order."
    ),
    "mealplan": (
        "Generates or edits a weekly meal plan (Monday-Friday). "
        "Use when the user asks for a meal plan or wants to swap a day in their plan. "
        "Requires menu items to be fetched first."
    ),
    "execution": (
        "Places a confirmed order. Use ONLY when the user has clearly chosen a "
        "specific item to order (by name or by confirming a recommendation)."
    ),
    "learning": (
        "Saves preferences, dietary restrictions, and order events to memory. "
        "Use when the user expresses a preference, allergy, or restriction, "
        "OR after an order is placed to remember the choice."
    ),
}

PLANNER_SYSTEM_PROMPT = """You are the Planner for a corporate catering assistant.
Given a user message, classify it into an intent, extract structured constraints, and \
flag compound signals. The orchestrator composes the execution flow deterministically \
from your output — you do NOT pick agents or order steps.

Available agents (shown for context so you can reason about what the system can do):
{agent_descriptions}

INTENTS — choose exactly ONE primary intent:
- "order_meal"         — vague order ("I want lunch", "get me something Thai"). \
The user has NOT named a specific dish, so suggestions are needed first.
- "confirm_order"      — user explicitly chose an item ("I'll have the Pad Thai", \
"yes, order it", "I love tofu. I'll have it today"). Extract ``selected_item``.
- "get_recommendation" — asking for suggestions ("what's good?", "recommend something").
- "declare_preference" — stating a preference WITHOUT any order or recommendation request.
- "create_mealplan"    — weekly meal plan creation, or swapping / replacing / updating \
a day in an existing plan.
- "submit_mealplan"    — approving / finalising an existing meal plan ("submit my plan", \
"looks good, confirm it").
- "check_order_status" — asking about an existing order.
- "ask_question"       — general question about menu items, ingredients, etc.
- "out_of_scope"       — request has NOTHING to do with meals, food, catering, dietary \
preferences, or the service. Examples: "What's the weather?", "Write me a poem", \
"Help me with my taxes", "Tell me a joke".

CONSTRAINTS — flat object. Extract only what the user stated. Keys:
- budget (int), dietary (string), cuisine (string), meal_type (string),
  selected_item (string), preference (string).

COMPOUND FLAGS — flat object of booleans. Keys:
- "has_preference": true when the user expressed a preference / allergy / dietary \
restriction alongside another intent. Look for ANY of:
    - "I love …", "I like …", "I enjoy …", "I prefer …", "my favourite …"
    - "I'm allergic …", "I'm vegetarian/vegan", "I don't eat …", "I avoid …"
    - "I hate …", "I can't have …", "no nuts", "gluten-free for me"
  Set this flag even when the main request is a recommendation or an order — the \
orchestrator will append a learning step to persist it.

MEAL PLAN CONTEXT:
{meal_plan_context}
When the user references swapping, replacing, changing, or updating items in the meal \
plan, classify as "create_mealplan". If they also state a preference (e.g. "not a fan \
of tofu, swap it"), set has_preference = true as well.

Respond ONLY with valid JSON. Do NOT include a "plan" field — the orchestrator builds \
the plan from the intent and flags.

{{"intent": "...", "constraints": {{...}}, "compound_flags": {{...}}}}
"""


def _build_system_prompt(
    available_agents: set[str],
    *,
    meal_plan: dict[str, Any] | None = None,
) -> str:
    """Build the planner system prompt with only the available agents."""
    descriptions = "\n".join(
        f"- **{name}**: {desc}" for name, desc in AGENT_CATALOG.items() if name in available_agents
    )
    if meal_plan:
        plan_lines = [f"  {day}: {entry.get('name', '—')}" for day, entry in meal_plan.items()]
        context = "The user has an ACTIVE meal plan:\n" + "\n".join(plan_lines)
    else:
        context = "No active meal plan in this session."
    return PLANNER_SYSTEM_PROMPT.format(agent_descriptions=descriptions, meal_plan_context=context)


class PlannerAgent:
    """Builds an execution plan from user messages.

    Supports two modes:
    - ``llm``: uses Claude to analyze compound requests and build plans.
    - ``keyword``: deterministic fallback matching the old IntentAgent behavior.
    """

    def __init__(
        self,
        *,
        mode: Literal["keyword", "llm"] = "keyword",
        anthropic_client: anthropic.AsyncAnthropic | None = None,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self.mode = mode
        self.anthropic_client = anthropic_client
        self.model = model

        if mode == "llm" and anthropic_client is None:
            logger.warning("planner_agent_no_client", fallback="keyword")

    async def plan(
        self,
        state: WorkflowState,
        available_agents: set[str],
    ) -> dict[str, Any]:
        """Produce an execution plan for the current message.

        Returns a dict with:
        - intent: primary intent string
        - constraints: extracted constraints dict
        - plan: list of {"agent": str, "reason": str} steps
        """
        user_message = ""
        if state.messages:
            user_message = state.messages[-1].get("content", "")

        if self.mode == "llm" and self.anthropic_client is not None:
            result = await self._plan_llm(user_message, available_agents, state=state)
        else:
            result = self._plan_keyword(user_message, available_agents, state=state)

        # Apply to state
        state.intent = result["intent"]
        state.constraints = {**state.constraints, **result.get("constraints", {})}
        state.last_result = result

        logger.info(
            "plan_created",
            trace_id=state.trace_id,
            mode=self.mode,
            intent=result["intent"],
            constraints=result.get("constraints", {}),
            steps=[s["agent"] for s in result.get("plan", [])],
        )

        return result

    # --- LLM planning ---------------------------------------------------------

    async def _plan_llm(
        self,
        message: str,
        available_agents: set[str],
        *,
        state: WorkflowState | None = None,
    ) -> dict[str, Any]:
        """Classify the message with Claude, then compose the plan via the flow router.

        The LLM is responsible for intent + constraint + flag extraction ONLY.
        Plan composition lives in ``flow_router.compose_plan`` so the keyword
        fallback and the LLM path produce identical structures for the same
        classification. Falls back to the keyword planner on any API, parse,
        or validation failure.
        """
        try:
            from plateful.core.flow_router import compose_plan
            from plateful.core.observability import null_llm_trace, trace_llm_call

            meal_plan = state.meal_plan if state else None
            system_prompt = _build_system_prompt(available_agents, meal_plan=meal_plan or None)

            # Get tracing context for LLM generation recording
            tracing = getattr(state, "_tracing", None) if state else None

            if tracing is not None and tracing.is_active:
                gen_ctx = trace_llm_call(
                    tracing, name="planner.llm", model=self.model, input_data=message
                )
            else:
                gen_ctx = null_llm_trace()

            async with gen_ctx as gen:
                response = await self.anthropic_client.messages.create(  # type: ignore[union-attr]
                    model=self.model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": message}],
                    max_tokens=512,
                )
                gen.update(
                    output=response.content[0].text,  # type: ignore[union-attr]
                    usage_details={
                        "input": response.usage.input_tokens,
                        "output": response.usage.output_tokens,
                    },
                ).end()

            text = response.content[0].text  # type: ignore[union-attr]
            # Strip markdown code fences that Claude sometimes adds
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
            parsed = json.loads(text)

            # Validate and sanitize
            intent = parsed.get("intent", "get_recommendation")
            constraints = parsed.get("constraints", {})
            if not isinstance(constraints, dict):
                constraints = {}
            compound_flags = parsed.get("compound_flags", {})
            if not isinstance(compound_flags, dict):
                compound_flags = {}

            # Out-of-scope short-circuits: no plan, no constraints.
            if intent == "out_of_scope":
                return {"intent": "out_of_scope", "constraints": {}, "plan": []}

            plan = compose_plan(intent, available_agents, compound_flags=compound_flags)

            if not plan:
                # Unknown intent or all steps filtered out — fall back to keyword
                # so we don't silently return nothing to the orchestrator.
                return self._plan_keyword(message, available_agents, state=state)

            return {"intent": intent, "constraints": constraints, "plan": plan}

        except Exception:
            logger.warning("llm_planner_fallback", reason="api_or_parse_error", exc_info=True)
            return self._plan_keyword(message, available_agents, state=state)

    # --- Keyword planning (fallback) ------------------------------------------

    _MEALPLAN_SUBMIT_SIGNALS: ClassVar[list[str]] = [
        "submit",
        "confirm",
        "finalize",
        "approve",
        "looks good",
        "go ahead",
        "place the order",
        "order the plan",
    ]

    _MEALPLAN_SWAP_SIGNALS: ClassVar[list[str]] = [
        "swap",
        "switch",
        "replace",
        "change",
        "update the meal plan",
        "update the plan",
        "update my meal plan",
        "update my plan",
    ]

    def _plan_keyword(
        self,
        message: str,
        available_agents: set[str],
        *,
        state: WorkflowState | None = None,
    ) -> dict[str, Any]:
        """Deterministic planning using keyword matching.

        Classifies intent + constraints + compound flags with simple regex /
        keyword rules, then delegates plan composition to the same
        ``compose_plan`` helper used by the LLM path. This keeps both modes
        in lockstep: changing ``INTENT_FLOWS`` updates both planners at once.
        """
        from plateful.agents.intent import IntentAgent
        from plateful.core.flow_router import compose_plan
        from plateful.core.preference_signals import has_preference_signal

        # Reuse IntentAgent's keyword classification
        agent = IntentAgent(mode="keyword")
        intent = agent._classify_keyword(message)
        constraints = agent._extract_constraints(message)

        # Override: if there's an active meal plan, detect swap or submit intents
        has_active_plan = bool(state and state.meal_plan)
        msg_lower = message.lower()
        if has_active_plan:
            if any(s in msg_lower for s in self._MEALPLAN_SWAP_SIGNALS):
                intent = "create_mealplan"
            elif any(s in msg_lower for s in self._MEALPLAN_SUBMIT_SIGNALS):
                intent = "submit_mealplan"

        compound_flags = {"has_preference": has_preference_signal(message)}

        if intent == "out_of_scope":
            return {"intent": "out_of_scope", "constraints": {}, "plan": []}

        plan = compose_plan(intent, available_agents, compound_flags=compound_flags)

        return {"intent": intent, "constraints": constraints, "plan": plan}
