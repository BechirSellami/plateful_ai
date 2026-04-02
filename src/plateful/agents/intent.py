from __future__ import annotations

import json
import re
from typing import Any, ClassVar, Literal

import anthropic
import structlog

from plateful.core.workflow import WorkflowState

logger = structlog.get_logger()

VALID_INTENTS = frozenset(
    {
        "order_meal",
        "get_recommendation",
        "create_mealplan",
        "check_order_status",
        "declare_preference",
        "ask_question",
    }
)

INTENT_SYSTEM_PROMPT = """You are the Intent Classifier for a catering assistant.
Analyze the user's message and extract:
1. intent: one of [order_meal, get_recommendation, create_mealplan, check_order_status, declare_preference, ask_question]
2. constraints: any mentioned constraints as a flat JSON object. Supported keys:
   - budget (integer, e.g. 25)
   - dietary (string, e.g. "vegetarian", "vegan", "halal", "kosher", "gluten-free", "keto")
   - cuisine (string, e.g. "thai", "italian", "mexican", "japanese", "indian", "chinese", "mediterranean")
   - meal_type (string, e.g. "breakfast", "lunch", "dinner", "snack")

Respond ONLY with valid JSON, no markdown or explanation:
{"intent": "...", "constraints": {...}}
"""


class IntentAgent:
    """Classifies user intent and extracts constraints from the message.

    Supports two modes:
    - ``keyword`` (default): fast, deterministic, no external calls.
    - ``llm``: uses Claude for nuanced classification. Falls back to
      keyword mode if the API call fails.
    """

    INTENT_KEYWORDS: ClassVar[dict[str, list[str]]] = {
        "order_meal": ["order", "buy", "get me", "i want", "i'd like", "purchase"],
        "get_recommendation": [
            "recommend",
            "suggest",
            "what should",
            "ideas",
            "options",
            "what's good",
        ],
        "create_mealplan": ["meal plan", "mealplan", "weekly", "plan my", "week"],
        "check_order_status": ["status", "where is", "track", "my order"],
        "declare_preference": [
            "allergic",
            "allergy",
            "don't eat",
            "vegetarian",
            "vegan",
            "prefer",
        ],
        "ask_question": ["what is", "how", "tell me about", "explain", "menu"],
    }

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
            logger.warning("intent_agent_no_client", fallback="keyword")

    async def run(self, state: WorkflowState) -> WorkflowState:
        user_message = ""
        if state.messages:
            user_message = state.messages[-1].get("content", "")

        if self.mode == "llm" and self.anthropic_client is not None:
            intent, constraints = await self._classify_llm(user_message)
        else:
            intent = self._classify_keyword(user_message)
            constraints = self._extract_constraints(user_message)

        state.intent = intent
        state.constraints = {**state.constraints, **constraints}
        state.last_result = {"intent": intent, "constraints": constraints}

        logger.info(
            "intent_classified",
            trace_id=state.trace_id,
            mode=self.mode,
            intent=intent,
            constraints=constraints,
        )

        return state

    # --- LLM classification ------------------------------------------------

    async def _classify_llm(self, message: str) -> tuple[str, dict[str, Any]]:
        """Classify intent via Claude. Falls back to keyword on any failure."""
        try:
            response = await self.anthropic_client.messages.create(  # type: ignore[union-attr]
                model=self.model,
                system=INTENT_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message}],
                max_tokens=256,
            )

            text = response.content[0].text  # type: ignore[union-attr]
            parsed = json.loads(text)

            intent = parsed.get("intent", "get_recommendation")
            if intent not in VALID_INTENTS:
                intent = "get_recommendation"

            constraints = parsed.get("constraints", {})
            if not isinstance(constraints, dict):
                constraints = {}

            return intent, constraints

        except Exception:
            logger.warning("llm_intent_fallback", reason="api_or_parse_error")
            return self._classify_keyword(message), self._extract_constraints(message)

    # --- Keyword classification --------------------------------------------

    def _classify_keyword(self, message: str) -> str:
        message_lower = message.lower()
        for intent, keywords in self.INTENT_KEYWORDS.items():
            for keyword in keywords:
                if keyword in message_lower:
                    return intent
        return "get_recommendation"

    def _extract_constraints(self, message: str) -> dict[str, Any]:
        constraints: dict[str, Any] = {}
        message_lower = message.lower()

        # Budget extraction
        budget_match = re.search(r"under\s*\$?(\d+)", message_lower)
        if budget_match:
            constraints["budget"] = int(budget_match.group(1))

        # Meal type
        for meal in ["breakfast", "lunch", "dinner", "snack"]:
            if meal in message_lower:
                constraints["meal_type"] = meal
                break

        # Dietary
        for diet in ["vegetarian", "vegan", "halal", "kosher", "gluten-free", "keto"]:
            if diet in message_lower:
                constraints["dietary"] = diet
                break

        # Cuisine
        cuisines = [
            "thai",
            "italian",
            "mexican",
            "japanese",
            "indian",
            "chinese",
            "mediterranean",
        ]
        for cuisine in cuisines:
            if cuisine in message_lower:
                constraints["cuisine"] = cuisine
                break

        return constraints
