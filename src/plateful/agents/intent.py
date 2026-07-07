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
        "confirm_order",
        "get_recommendation",
        "create_mealplan",
        "submit_mealplan",
        "check_order_status",
        "declare_preference",
        "ask_question",
        "out_of_scope",
    }
)

INTENT_SYSTEM_PROMPT = """You are the Intent Classifier for a catering assistant.
Analyze the user's message and extract:
1. intent: one of [order_meal, confirm_order, get_recommendation, create_mealplan, submit_mealplan, check_order_status, declare_preference, ask_question, out_of_scope]
2. constraints: any mentioned constraints as a flat JSON object. Supported keys:
   - budget (integer, e.g. 25)
   - dietary (string, e.g. "vegetarian", "vegan", "halal", "kosher", "gluten-free", "keto")
   - cuisine (string, e.g. "thai", "italian", "mexican", "japanese", "indian", "chinese", "mediterranean")
   - meal_type (string, e.g. "breakfast", "lunch", "dinner", "snack")
   - selected_item (string, the specific menu item the user chose, e.g. "Grilled Chicken Bowl")

Intent classification rules:
- order_meal: the user wants to ORDER or EAT something but hasn't chosen a specific menu item yet. Examples: "I want chicken today", "Get me a salad", "Order lunch", "I'd like something spicy".
- confirm_order: the user is CONFIRMING a specific menu item to order, typically after seeing recommendations. Examples: "I'll take the Grilled Chicken Bowl", "Yes, order the first one", "Go with the Tofu Stir Fry", "That one please", "Order it", "Yes".
- get_recommendation: the user wants SUGGESTIONS but hasn't decided yet. Examples: "What should I eat?", "Recommend something healthy", "What's good today?".
- declare_preference: the user is stating a GENERAL preference, allergy, or restriction — NOT ordering. Examples: "I'm vegetarian", "I'm allergic to peanuts", "I prefer spicy food", "I don't eat pork".
- create_mealplan: the user wants to plan meals for multiple days. Examples: "Plan my meals for the week".
- submit_mealplan: the user wants to submit/confirm their existing meal plan as an order. Examples: "Submit my meal plan", "Confirm the plan", "Looks good, submit it".
- check_order_status: the user is asking about an existing order. Examples: "Where is my order?", "What's the status?".
- ask_question: the user is asking about the menu or service. Examples: "What's on the menu?", "How does this work?".
- out_of_scope: the request is UNRELATED to meals, food ordering, catering, dietary preferences, or the service. Examples: "What's the weather?", "Write me a poem", "Tell me a joke", "Help me with my taxes", "What time is it?", "Translate this to French".

Key distinctions:
- If the user mentions wanting to EAT or HAVE something specific (a food item), that is order_meal, NOT declare_preference.
- If the user is picking a specific item from recommendations (by name or number), that is confirm_order, NOT order_meal.
- declare_preference is only for general dietary rules or restrictions.
- If the message has NOTHING to do with food, meals, ordering, or catering, classify as out_of_scope.

For confirm_order, extract the selected item name into constraints.selected_item if mentioned.

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
        "submit_mealplan": [
            "submit my meal plan",
            "submit the meal plan",
            "submit meal plan",
            "confirm meal plan",
            "confirm the meal plan",
            "confirm my meal plan",
            "submit my plan",
            "submit the plan",
            "approve meal plan",
            "finalize meal plan",
            "go ahead with the plan",
            "go ahead with the meal plan",
            "looks good, submit",
            "submit it",
        ],
        "confirm_order": [
            "i'll take",
            "i'll have",
            "let me have",
            "let me get",
            "go with",
            "order the",
            "yes, order",
            "that one",
            "sounds good",
        ],
        "order_meal": ["order", "buy", "get me", "i want", "i'd like", "purchase"],
        "get_recommendation": [
            "recommend",
            "suggest",
            "what should",
            "ideas",
            "options",
            "what's good",
        ],
        "create_mealplan": [
            "meal plan",
            "mealplan",
            "weekly",
            "plan my",
            "week",
            "swap monday",
            "swap tuesday",
            "swap wednesday",
            "swap thursday",
            "swap friday",
            "change monday",
            "change tuesday",
            "change wednesday",
            "change thursday",
            "change friday",
        ],
        "check_order_status": ["status", "where is", "track", "my order"],
        "declare_preference": [
            "allergic",
            "allergy",
            "don't eat",
            "i love",
            "i like",
            "i enjoy",
            "i hate",
            "i avoid",
            "i can't have",
            "i cannot have",
            "i don't like",
            "i no longer",
            "not anymore",
            "anymore",
            "vegetarian",
            "vegan",
            "prefer",
        ],
        "ask_question": ["what is", "how", "tell me about", "explain", "menu"],
    }

    # Words that indicate the message is at least food / catering related,
    # even if no specific intent keyword matched (e.g. "any salads today?").
    FOOD_SIGNALS: ClassVar[list[str]] = [
        "food",
        "meal",
        "lunch",
        "dinner",
        "breakfast",
        "snack",
        "eat",
        "hungry",
        "cook",
        "dish",
        "recipe",
        "salad",
        "soup",
        "bowl",
        "sandwich",
        "burger",
        "pizza",
        "sushi",
        "pasta",
        "rice",
        "chicken",
        "beef",
        "fish",
        "tofu",
        "vegan",
        "vegetarian",
        "calories",
        "nutrition",
        "diet",
        "healthy",
        "catering",
        "delivery",
        "price",
        "cheap",
        "expensive",
        "spicy",
        "sweet",
        "dessert",
        "drink",
        "coffee",
        "tea",
        "menu",
    ]

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

        # No intent keyword matched — check if the message is food-related at all
        if self._has_food_signal(message_lower):
            return "get_recommendation"

        return "out_of_scope"

    @classmethod
    def _has_food_signal(cls, message_lower: str) -> bool:
        """Check if the message contains any food/catering related word."""
        for signal in cls.FOOD_SIGNALS:
            if len(signal) <= 4:
                # Short words need word-boundary matching to avoid
                # false positives (e.g. "eat" in "weather").
                if re.search(rf"\b{re.escape(signal)}\b", message_lower):
                    return True
            elif signal in message_lower:
                return True
        return False

    # Patterns that introduce a menu item name in a confirm-order message.
    # Capture group 1 is the item name (everything after the trigger phrase,
    # stripped of trailing punctuation).
    _SELECTED_ITEM_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"i'll take (?:the )?(.+)", re.IGNORECASE),
        re.compile(r"i'll have (?:the )?(.+)", re.IGNORECASE),
        re.compile(r"let me (?:have|get) (?:the )?(.+)", re.IGNORECASE),
        re.compile(r"go with (?:the )?(.+)", re.IGNORECASE),
        re.compile(r"order the (.+)", re.IGNORECASE),
    ]

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

        # Selected item — extract from confirm-order phrases like
        # "I'll take the Tofu Stir Fry" → selected_item = "Tofu Stir Fry"
        for pattern in self._SELECTED_ITEM_PATTERNS:
            m = pattern.search(message)
            if m:
                # Strip trailing punctuation / whitespace but preserve
                # the original casing from the user's message.
                item_name = m.group(1).strip().rstrip(".,!?;:")
                if item_name:
                    constraints["selected_item"] = item_name
                break

        return constraints
