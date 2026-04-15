"""Tools for the Recommendation Agent to rank and score menu items."""

from typing import Any


def rank_items(
    items: list[dict[str, Any]],
    profile: dict[str, Any],
    *,
    user_message: str = "",
) -> list[dict[str, Any]]:
    """Score and rank menu items by preference match.

    Uses a simple scoring heuristic based on user profile signals.
    The user's *current request* (``user_message``) is given the
    highest weight so that explicit asks always outrank stored prefs.

    Returns items sorted by score (highest first) with score attached.
    """
    scored = []
    preferences = [p.lower() for p in profile.get("preferences", [])]
    favorite_cuisines = [c.lower() for c in profile.get("favorite_cuisines", [])]
    disliked = [d.lower() for d in profile.get("disliked_items", [])]
    budget_pref = profile.get("budget_preference", "")

    # Extract meaningful keywords from the current request (highest priority)
    _stop_words = {
        "i",
        "me",
        "my",
        "want",
        "would",
        "like",
        "to",
        "a",
        "an",
        "the",
        "or",
        "and",
        "some",
        "today",
        "please",
        "get",
        "have",
        "for",
        "with",
        "of",
        "in",
        "on",
        "it",
        "is",
        "be",
        "do",
    }
    request_words = {w for w in user_message.lower().split() if len(w) > 2 and w not in _stop_words}

    for item in items:
        score = 50.0  # base score

        item_text = (
            f"{item.get('name', '')} {item.get('description', '')} "
            f"{item.get('cuisine', '')} {item.get('category', '')}"
        ).lower()

        # --- Current request match (strongest signal) ---
        for word in request_words:
            if word in item_text:
                score += 25.0

        # --- Stored preference signals (secondary) ---

        # Cuisine match bonus
        if item.get("cuisine", "").lower() in favorite_cuisines:
            score += 10.0

        # Preference keyword matching
        for pref in preferences:
            pref_words = pref.split()
            for word in pref_words:
                if len(word) > 3 and word in item_text:
                    score += 5.0
                    break

        # Penalize disliked items
        for dislike in disliked:
            dislike_words = dislike.split()
            for word in dislike_words:
                if len(word) > 3 and word in item_text:
                    score -= 30.0
                    break

        # Budget alignment
        if budget_pref and "under" in str(budget_pref).lower():
            price = float(item.get("price_usd", 0))
            if price <= 15:
                score += 5.0
            elif price >= 22:
                score -= 5.0

        # Healthy category bonus (common preference)
        if item.get("category") == "healthy":
            score += 5.0

        scored.append({**item, "score": round(score, 1)})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def format_recommendations_prompt(
    items: list[dict[str, Any]],
    profile: dict[str, Any],
    constraints: dict[str, Any],
    *,
    user_message: str = "",
    allergen_warning: str = "",
) -> str:
    """Format menu items and profile into a prompt for the LLM to generate recommendations."""
    items_text = "\n".join(
        f"- {item['name']} (${item.get('price_usd', '?')}, {item.get('category', '?')}, "
        f"{item.get('cuisine', '?')}, {item.get('calories', '?')} cal)"
        f"{' [score: ' + str(item['score']) + ']' if 'score' in item else ''}"
        for item in items
    )

    request_text = ""
    if user_message:
        request_text = f'\nUser\'s current request: "{user_message}"'

    profile_text = ""
    if profile.get("preferences"):
        profile_text += f"\nStored preferences: {', '.join(profile['preferences'])}"
    if profile.get("dietary_restrictions"):
        profile_text += f"\nDietary restrictions: {', '.join(profile['dietary_restrictions'])}"
    if profile.get("allergies"):
        profile_text += f"\nAllergies: {', '.join(profile['allergies'])}"
    if profile.get("budget_preference"):
        profile_text += f"\nBudget: {profile['budget_preference']}"

    constraints_text = ""
    if constraints:
        parts = [f"{k}: {v}" for k, v in constraints.items()]
        constraints_text = f"\nConstraints: {', '.join(parts)}"

    allergen_text = ""
    if allergen_warning:
        allergen_text = (
            f"\n\nIMPORTANT ALLERGEN CONFLICT:\n{allergen_warning}\n"
            "You MUST start your response by clearly warning the user about this "
            "allergen conflict before making alternative suggestions."
        )

    return f"""Available items (pre-filtered and scored):
{items_text}
{request_text}
User profile (stored preferences — secondary to current request):{profile_text or " No profile data yet"}
{constraints_text}{allergen_text}

Prioritise items that match the user's current request. Use stored preferences \
only as tie-breakers or extra context. Pick the top 3 items and explain briefly \
why each is a good match. Be concise and friendly."""
