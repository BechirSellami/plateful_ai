"""Planner Agent: builds an execution plan from a user message.

The LLM builds the ordered agent plan directly (dynamic planning) — there
is no deterministic router composing it from the intent. The
``AGENT_CONTRACTS`` registry is the single source of truth for what each
agent requires/produces; this module renders it straight into the prompt
so the model reasons over the same dependency graph the downstream Plan
Validator (``orchestrator.resolve_validated_plan``) checks the plan
against. That validator — not this module — is what actually gates unsafe
or contract-violating plans; the LLM path here only does structural
sanitization (drop malformed/unavailable-agent steps) so garbage JSON
can't crash the caller.

Falls back to keyword-based intent classification (and deterministic
``compose_plan`` routing) when no LLM is available, the API call fails, or
the model's plan is empty/unparseable after sanitization.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Literal

import anthropic
import structlog

from plateful.core.agent_contracts import AGENT_CONTRACTS
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
Given a user message, classify it into an intent, extract structured constraints, flag \
compound signals, AND build the ordered execution plan yourself — a list of agent steps. \
There is no separate router: you decide which agents run and in what order, subject to \
the contract rules below. A Plan Validator checks your plan against these same contracts \
before anything runs and replaces it with a safe deterministic fallback if it is invalid \
— so an invalid plan is never executed, but a plan that skips a safety step is still a \
bug worth avoiding.

Available agents. "requires" / "requires one of" are OTHER STEPS' outputs your plan must \
already have produced earlier (or that CONTEXT below says already exist this session) \
before this agent can run; "produces" is what it adds for later steps to use:
{agent_descriptions}

PLAN RULES:
1. SAFETY-CRITICAL: never plan "execution" using a named item (selected_item) alone. \
"execution" must be preceded by "menu" in THIS plan, UNLESS CONTEXT below already shows \
filtered menu_items, recommendations, or an existing meal_plan available. The Menu \
Agent's deterministic allergen filter is the only thing that guarantees a named item is \
safe to order — skipping it is a bug no matter how confident you are the item is safe. \
When in doubt, include "menu".
2. A step's required inputs must already be produced by an earlier step in your plan, or \
already available per CONTEXT. If not, insert the producing agent earlier in the plan.
3. "learning" (and any other post-action agent) must be the LAST step(s) in the plan.
4. Only use agents from the list above. Keep plans minimal — do not include an agent \
that has nothing to contribute to this specific request.

CONTEXT — what's already available this turn, before your plan runs:
{context_summary}

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
- budget (int) — maximum dollar amount.
- dietary (string) — dietary restriction, e.g. "vegetarian", "vegan", "halal", "keto".
- cuisine (string) — a cuisine ORIGIN, e.g. "thai", "italian", "japanese". \
NEVER put a food item name here (e.g. "pasta" is NOT a cuisine — "italian" is).
- meal_type (string) — "breakfast", "lunch", "dinner", or "snack".
- selected_item (string) — the specific menu item the user chose to order.
- preference (string) — the stated preference or restriction.
- food_keywords (list[string]) — specific food items or categories the user mentioned, \
e.g. ["pasta", "sandwich"]. Use this when the user asks for a food type that is NOT \
a cuisine. Multiple values are allowed when the user says "or" / "and".

COMPOUND FLAGS — flat object of booleans. Keys:
- "has_preference": true when the user expressed a preference / allergy / dietary \
restriction alongside another intent. Look for ANY of:
    - "I love …", "I like …", "I enjoy …", "I prefer …", "my favourite …"
    - "I'm allergic …", "I'm vegetarian/vegan", "I don't eat …", "I avoid …"
    - "I hate …", "I can't have …", "no nuts", "gluten-free for me"
  Set this flag even when the main request is a recommendation or an order — include a \
"learning" step in your plan to persist it, in addition to whatever the primary intent \
needs. Don't duplicate "learning" if it's already the last step for another reason.

MEAL PLAN CONTEXT:
{meal_plan_context}
When the user references swapping, replacing, changing, or updating items in the meal \
plan, classify as "create_mealplan". If they also state a preference (e.g. "not a fan \
of tofu, swap it"), set has_preference = true as well.

EXAMPLES:

User: "What should I eat today?"
{{"intent": "get_recommendation", "constraints": {{}}, "compound_flags": {{}}, "plan": \
[{{"agent": "memory", "reason": "check dietary restrictions"}}, {{"agent": "menu", \
"reason": "fetch today's safe items"}}, {{"agent": "recommendation", "reason": "rank and \
suggest"}}]}}

User: "I love tofu. I'll have it today"
{{"intent": "confirm_order", "constraints": {{"selected_item": "tofu"}}, \
"compound_flags": {{"has_preference": true}}, "plan": [{{"agent": "memory", "reason": \
"check allergies"}}, {{"agent": "menu", "reason": "filter safe items before ordering"}}, \
{{"agent": "execution", "reason": "place the order"}}, {{"agent": "learning", "reason": \
"remember the preference"}}]}}

User: "Looks good, submit the meal plan" (CONTEXT shows meal_plan already available)
{{"intent": "submit_mealplan", "constraints": {{}}, "compound_flags": {{}}, "plan": \
[{{"agent": "execution", "reason": "submit the existing meal plan"}}, {{"agent": \
"learning", "reason": "record the order"}}]}}
(No "menu" needed here — the meal plan's items were already filtered when it was built.)

Respond ONLY with valid JSON in this exact shape:
{{"intent": "...", "constraints": {{...}}, "compound_flags": {{...}}, "plan": \
[{{"agent": "...", "reason": "..."}}]}}
"""


def _contract_summary(name: str) -> str:
    """Render an agent's declared contract as one line for the prompt.

    Pulled live from ``AGENT_CONTRACTS`` rather than hand-maintained prose
    so this can never drift from what ``validate_plan`` actually checks.
    """
    contract = AGENT_CONTRACTS.get(name)
    if contract is None:
        return "no declared contract"

    parts: list[str] = []
    if contract.requires:
        parts.append(f"requires: {', '.join(contract.requires)}")
    if contract.requires_any:
        groups = " OR ".join(f"({', '.join(g)})" for g in contract.requires_any)
        parts.append(f"requires one of: {groups}")
    if contract.optional:
        parts.append(f"optional: {', '.join(contract.optional)}")
    if contract.produces:
        parts.append(f"produces: {', '.join(contract.produces)}")
    if contract.post_action:
        parts.append("must run LAST")
    if contract.side_effect:
        parts.append("SIDE EFFECT")
    return "; ".join(parts) if parts else "no inputs/outputs declared"


def _context_summary(state: WorkflowState | None) -> str:
    """Summarize what's already available this session, so the planner
    knows when a prerequisite agent can legitimately be skipped (e.g.
    submit_mealplan doesn't need "menu" again if menu_items already ran)."""

    def _yn(value: bool) -> str:
        return "yes" if value else "no"

    return (
        f"- filtered menu_items already available: {_yn(bool(state and state.menu_items))}\n"
        f"- meal_plan already available: {_yn(bool(state and state.meal_plan))}\n"
        f"- recommendations already available: {_yn(bool(state and state.recommendations))}"
    )


def _build_system_prompt(
    available_agents: set[str],
    *,
    state: WorkflowState | None = None,
) -> str:
    """Build the planner system prompt with only the available agents."""
    descriptions = "\n".join(
        f"- **{name}**: {desc}\n  contract — {_contract_summary(name)}"
        for name, desc in AGENT_CATALOG.items()
        if name in available_agents
    )
    meal_plan = state.meal_plan if state else None
    if meal_plan:
        plan_lines = [f"  {day}: {entry.get('name', '—')}" for day, entry in meal_plan.items()]
        meal_plan_context = "The user has an ACTIVE meal plan:\n" + "\n".join(plan_lines)
    else:
        meal_plan_context = "No active meal plan in this session."
    return PLANNER_SYSTEM_PROMPT.format(
        agent_descriptions=descriptions,
        meal_plan_context=meal_plan_context,
        context_summary=_context_summary(state),
    )


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
        model: str = "claude-sonnet-5",
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

        result: dict[str, Any]
        if not user_message.strip():
            result = {
                "intent": "out_of_scope",
                "constraints": {},
                "compound_flags": {},
                "plan": [],
            }
        elif self.mode == "llm" and self.anthropic_client is not None:
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
        """Classify the message AND build the ordered plan directly with Claude.

        This method only does structural sanitization on the model's plan —
        drop malformed steps and steps naming an agent that isn't in
        ``available_agents``. It does NOT check contracts; that's the Plan
        Validator's job downstream (``orchestrator.resolve_validated_plan``),
        which is the actual safety gate and is the only thing that can
        reject/replace a plan. Falls back to the keyword planner (which
        still uses deterministic ``compose_plan`` routing) on any API,
        parse, or sanitization failure — including an empty plan.
        """
        try:
            from plateful.core.observability import null_llm_trace, trace_llm_call

            system_prompt = _build_system_prompt(available_agents, state=state)

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
                    thinking={"type": "disabled"},
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
                return {
                    "intent": "out_of_scope",
                    "constraints": {},
                    "compound_flags": {},
                    "plan": [],
                }

            plan = self._sanitize_plan(parsed.get("plan"), available_agents)

            if not plan:
                # Empty, malformed, or entirely-unavailable-agent plan —
                # fall back to keyword so we don't silently return nothing
                # to the orchestrator. Note this is a parsing-layer
                # concern, not the safety gate: a structurally valid but
                # contract-violating plan is returned as-is and caught
                # downstream by resolve_validated_plan.
                return self._plan_keyword(message, available_agents, state=state)

            return {
                "intent": intent,
                "constraints": constraints,
                "compound_flags": compound_flags,
                "plan": plan,
            }

        except Exception:
            logger.warning("llm_planner_fallback", reason="api_or_parse_error", exc_info=True)
            return self._plan_keyword(message, available_agents, state=state)

    @staticmethod
    def _sanitize_plan(raw_plan: Any, available_agents: set[str]) -> list[dict[str, Any]]:
        """Structural sanitization only — no contract checks here.

        Drops entries that aren't well-formed ``{"agent": str, ...}`` dicts
        or that name an agent outside ``available_agents`` (covers both a
        hallucinated agent name and one that's simply not registered in
        this environment). Order is preserved; duplicates are left as-is
        since a repeated step is a contract/validator concern, not a
        parsing one.
        """
        if not isinstance(raw_plan, list):
            return []

        sanitized: list[dict[str, Any]] = []
        for step in raw_plan:
            if not isinstance(step, dict):
                continue
            agent_name = step.get("agent")
            if not isinstance(agent_name, str) or agent_name not in available_agents:
                continue
            reason = step.get("reason")
            sanitized.append(
                {"agent": agent_name, "reason": reason if isinstance(reason, str) else agent_name}
            )
        return sanitized

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
        keyword rules, then composes the plan via ``compose_plan`` (static
        ``INTENT_FLOWS`` routing). This is the degraded-mode fallback for
        when the LLM is unavailable or its plan doesn't survive
        sanitization — unlike ``_plan_llm``, this path is always
        contract-valid by construction (see
        ``test_intent_flow_matches_contracts``).
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
