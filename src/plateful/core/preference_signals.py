"""Shared preference-detection patterns used by planner, learning agent, and intent classifier."""

# Phrases that indicate the user is expressing a food preference,
# dietary restriction, allergy, or taste (positive or negative).
# Used by:
#   - PlannerAgent._plan_keyword() to append the learning step
#   - LearningAgent._collect_events() to capture preferences regardless of intent
#   - IntentAgent.INTENT_KEYWORDS["declare_preference"] for intent classification
PREFERENCE_SIGNALS: list[str] = [
    # Positive preferences
    "i love",
    "i like",
    "i enjoy",
    "i prefer",
    "my favourite",
    "my favorite",
    # Negative preferences / restrictions
    "i hate",
    "i avoid",
    "i can't have",
    "i cannot have",
    "i don't like",
    "i don't eat",
    "i no longer",
    "not anymore",
    "anymore",
    # Dietary / allergen declarations
    "allergic",
    "allergy",
    "vegetarian",
    "vegan",
    "gluten-free",
    "halal",
    "kosher",
]


def has_preference_signal(message: str) -> bool:
    """Return True if the message contains any preference signal."""
    msg_lower = message.lower()
    return any(sig in msg_lower for sig in PREFERENCE_SIGNALS)
