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
Given a user message, produce a JSON execution plan.

Available agents:
{agent_descriptions}

Rules:
- Analyze the FULL message. It may contain MULTIPLE intents (e.g. a preference AND an order).
- Output an ordered list of agent steps to fulfill ALL parts of the request.
- Each step has: "agent" (registry name), "reason" (brief explanation).
- Deduplicate: if "learning" appears multiple times, keep one at the END (it captures everything).
- "menu" must come before "recommendation" (recommendations need menu data).
- "memory" should come before "menu" or "recommendation" (preferences inform filtering).
- "execution" requires the user to have explicitly chosen an item. Do NOT add execution \
for vague requests like "I want chicken" — that needs recommendation first.

PREFERENCE DETECTION — always include "learning" when ANY of these appear:
- "I love …", "I like …", "I enjoy …", "I prefer …", "my favourite …"
- "I'm allergic …", "I'm vegetarian/vegan", "I don't eat …", "I avoid …"
- "I hate …", "I can't have …", "no nuts", "gluten-free for me"
A preference can appear ALONGSIDE another request. Look for it even if the main \
request is a recommendation or order.

Flow patterns:
- Preference ONLY (no order or rec request): "learning".
- Recommendation ONLY (no preference stated): memory → menu → recommendation.
- Preference + recommendation (e.g. "I love spicy food, what do you recommend?"): \
memory → menu → recommendation → learning.
- Confirm a specific item: execution → learning.
- Preference + order: memory → menu → execution → learning.
- Preference + vague order (needs suggestions first): memory → menu → recommendation → learning.

Also extract:
- "intent": the PRIMARY intent (order_meal, confirm_order, get_recommendation, \
declare_preference, create_mealplan, check_order_status, ask_question)
- "constraints": extracted details as a flat object. Keys: budget (int), dietary (string), \
cuisine (string), meal_type (string), selected_item (string), preference (string).

Respond ONLY with valid JSON:
{{"intent": "...", "constraints": {{...}}, "plan": [{{"agent": "...", "reason": "..."}}]}}
"""


def _build_system_prompt(available_agents: set[str]) -> str:
    """Build the planner system prompt with only the available agents."""
    descriptions = "\n".join(
        f"- **{name}**: {desc}" for name, desc in AGENT_CATALOG.items() if name in available_agents
    )
    return PLANNER_SYSTEM_PROMPT.format(agent_descriptions=descriptions)


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
            result = await self._plan_llm(user_message, available_agents)
        else:
            result = self._plan_keyword(user_message, available_agents)

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

    async def _plan_llm(self, message: str, available_agents: set[str]) -> dict[str, Any]:
        """Use Claude to build an execution plan. Falls back to keyword on failure."""
        try:
            system_prompt = _build_system_prompt(available_agents)

            response = await self.anthropic_client.messages.create(  # type: ignore[union-attr]
                model=self.model,
                system=system_prompt,
                messages=[{"role": "user", "content": message}],
                max_tokens=512,
            )

            text = response.content[0].text  # type: ignore[union-attr]
            parsed = json.loads(text)

            # Validate and sanitize
            intent = parsed.get("intent", "get_recommendation")
            constraints = parsed.get("constraints", {})
            if not isinstance(constraints, dict):
                constraints = {}

            plan = parsed.get("plan", [])
            if not isinstance(plan, list):
                plan = []

            # Filter out agents not in registry
            plan = [s for s in plan if isinstance(s, dict) and s.get("agent") in available_agents]

            if not plan:
                # LLM returned empty plan — fall back to keyword
                return self._plan_keyword(message, available_agents)

            return {"intent": intent, "constraints": constraints, "plan": plan}

        except Exception:
            logger.warning("llm_planner_fallback", reason="api_or_parse_error")
            return self._plan_keyword(message, available_agents)

    # --- Keyword planning (fallback) ------------------------------------------

    # Patterns that signal a preference statement
    _PREFERENCE_SIGNALS: ClassVar[list[str]] = [
        "i love",
        "i like",
        "i enjoy",
        "i prefer",
        "i hate",
        "i avoid",
        "i can't have",
        "i don't eat",
        "allergic",
        "allergy",
        "vegetarian",
        "vegan",
        "gluten-free",
        "my favourite",
        "my favorite",
    ]

    def _plan_keyword(self, message: str, available_agents: set[str]) -> dict[str, Any]:
        """Deterministic planning using keyword matching.

        Detects compound intents: if the message contains a preference signal
        AND another intent (recommendation, order), the learning agent is
        appended to persist the preference.
        """
        from plateful.agents.intent import IntentAgent
        from plateful.core.flow_router import get_flow_for_intent

        # Reuse IntentAgent's keyword classification
        agent = IntentAgent(mode="keyword")
        intent = agent._classify_keyword(message)
        constraints = agent._extract_constraints(message)

        # Detect embedded preference
        msg_lower = message.lower()
        has_preference = any(sig in msg_lower for sig in self._PREFERENCE_SIGNALS)

        # Map to plan via the existing flow router
        flow = get_flow_for_intent(intent, available_agents)
        steps = flow["steps"]

        # Convert flow steps to plan format (skip "understand" — that's the planner itself)
        plan = [
            {"agent": s["agent"], "reason": f"Flow step: {s['name']}"}
            for s in steps
            if s["name"] != "understand" and s["agent"] in available_agents
        ]

        # If a preference is embedded alongside a non-preference intent, append learning
        if (
            has_preference
            and intent != "declare_preference"
            and "learning" in available_agents
            and not any(s["agent"] == "learning" for s in plan)
        ):
            plan.append({"agent": "learning", "reason": "Persist user preference"})

        return {"intent": intent, "constraints": constraints, "plan": plan}
