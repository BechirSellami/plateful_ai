from typing import Any, ClassVar

import structlog

from plateful.core.workflow import WorkflowState

logger = structlog.get_logger()

INTENT_SYSTEM_PROMPT = """You are the Intent Classifier for a catering assistant.
Analyze the user's message and extract:
1. intent: one of [order_meal, get_recommendation, create_mealplan, check_order_status, declare_preference, ask_question]
2. constraints: any mentioned constraints (budget, dietary, cuisine, meal_type, time)

Respond in JSON format:
{"intent": "...", "constraints": {...}}
"""


class IntentAgent:
    """Classifies user intent and extracts constraints from the message.

    For v1, uses keyword-based classification (no LLM call needed).
    Can be upgraded to LLM-based classification in future phases.
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

    async def run(self, state: WorkflowState) -> WorkflowState:
        user_message = ""
        if state.messages:
            user_message = state.messages[-1].get("content", "")

        intent = self._classify_intent(user_message)
        constraints = self._extract_constraints(user_message)

        state.intent = intent
        state.constraints = {**state.constraints, **constraints}
        state.last_result = {"intent": intent, "constraints": constraints}

        logger.info(
            "intent_classified",
            trace_id=state.trace_id,
            intent=intent,
            constraints=constraints,
        )

        return state

    def _classify_intent(self, message: str) -> str:
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
        import re

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
