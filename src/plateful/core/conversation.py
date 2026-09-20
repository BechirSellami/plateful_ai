"""Conversation transcript helpers.

The transcript is the *linguistic* memory layer: it lets the planner
resolve "it", "the second one", "instead", corrections, etc. It is NOT the
source of truth for what the system knows or is allowed to do — that stays
in the structured ``WorkflowState`` fields (menu_items, recommendations,
meal_plan, order) and the agent contracts / Plan Validator.

The WebSocket handler owns the session transcript and carries it forward
across turns; the planner stays stateless and just receives a bounded
window of it.
"""

from __future__ import annotations

import re
from typing import Any

from plateful.core.workflow import WorkflowState

# Recent-window cap. Catering sessions are short, so a plain window is
# enough for now — no summarization until we actually need it.
MAX_HISTORY_MESSAGES = 20

_FALLBACK_ASSISTANT_TURN = "Done."
ERROR_ASSISTANT_TURN = "Sorry, something went wrong on my end. Could you try again?"


def bounded_history(
    messages: list[dict[str, str]],
    *,
    limit: int = MAX_HISTORY_MESSAGES,
) -> list[dict[str, str]]:
    """Return the most recent messages in Messages-API shape.

    Guarantees the result starts with a ``user`` turn (an API requirement)
    and ends with a ``user`` turn: a trailing assistant message is prefill,
    which current models reject with a 400 — and the planner's job is to
    plan the latest *user* message anyway. Adjacent same-role turns are
    merged with a blank line; the API would combine them itself, this just
    keeps the window shape predictable. Messages missing a ``role`` are
    treated as ``user`` (the pre-multi-turn shape used by callers and tests).
    """
    normalized = [
        {"role": m.get("role", "user"), "content": m.get("content", "")}
        for m in messages
        if m.get("content", "").strip()
    ]
    # Take a wider window before merging so a merge doesn't shrink us
    # below the cap unnecessarily.
    window = normalized[-limit:] if limit > 0 else normalized

    merged: list[dict[str, str]] = []
    for m in window:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1] = {
                "role": m["role"],
                "content": merged[-1]["content"] + "\n\n" + m["content"],
            }
        else:
            merged.append(dict(m))

    # Must start with a user turn.
    while merged and merged[0]["role"] != "user":
        merged.pop(0)
    # Must end with a user turn (the message being planned).
    while merged and merged[-1]["role"] != "user":
        merged.pop()
    return merged


def render_assistant_turn(state: WorkflowState) -> str:
    """Render what the assistant "said" this turn as plain prose.

    When recommendations are on screen, the transcript leads with a
    numbered list of them in card order — that list, not the LLM prose,
    is what the user actually sees (the frontend hides the prose behind
    the cards), so it is what "the second one" must resolve against. The
    natural-language text follows. Falls back to a short rendering of the
    order / allergen conflict when no text was produced. Never returns an
    empty string, so the transcript keeps alternating.
    """
    if state.order:
        return state.recommendation_text or _render_order(state.order)

    parts: list[str] = []
    # The recommendation agent already folds the allergen warning into its
    # text; only render it separately when no text was produced.
    if state.allergen_conflicts and not state.recommendation_text:
        parts.append(_render_allergen_conflicts(state.allergen_conflicts))
    if state.recommendations:
        parts.append(_render_recommendation_list(state.recommendations))
    if state.recommendation_text:
        parts.append(state.recommendation_text)
    return "\n\n".join(parts) or _FALLBACK_ASSISTANT_TURN


def _render_recommendation_list(recommendations: list[dict[str, Any]]) -> str:
    """Numbered list mirroring the recommendation cards, in card order."""
    lines = ["Here are my recommendations:"]
    for i, item in enumerate(recommendations, 1):
        name = item.get("name", "item")
        price = item.get("price_usd")
        suffix = f" (${float(price):.2f})" if price is not None else ""
        lines.append(f"{i}. {name}{suffix}")
    return "\n".join(lines)


_ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
}
_ORDINAL_RE = re.compile(
    r"(?<!\w)(?:"  # \b would not fire before "#"
    r"(?P<num>\d+)(?:st|nd|rd|th)"  # 1st, 2nd, 3rd
    r"|(?:number|option|no\.?|#)\s*(?P<num2>\d+)"  # number 2, option 2, #2
    r"|(?P<word>first|second|third|fourth|fifth)"
    r"|(?P<last>last)"
    r")\b(?:\s+(?:one|option|item|recommendation|pick|choice))?",
    re.IGNORECASE,
)


def resolve_ordinal_reference(text: str, count: int) -> int | None:
    """Return the 0-based index a phrase like "the 2nd one" points at.

    Deterministic safety net for confirmations that reference a position
    in the list the user just saw ("the second one", "#3", "the last one").
    Returns None when there is no ordinal in ``text`` or it is out of
    range for ``count`` items.
    """
    if count <= 0:
        return None
    m = _ORDINAL_RE.search(text)
    if m is None:
        return None
    if m.group("last"):
        return count - 1
    if m.group("word"):
        n = _ORDINAL_WORDS[m.group("word").lower()]
    else:
        n = int(m.group("num") or m.group("num2"))
    return n - 1 if 1 <= n <= count else None


def _render_order(order: dict[str, Any]) -> str:
    names = ", ".join(str(i.get("name", "item")) for i in order.get("items", []))
    total = float(order.get("total_usd", 0) or 0)
    order_id = order.get("order_id", "?")
    if order.get("status") == "pending_approval":
        return (
            f"Order #{order_id} ({names}, ${total:.2f}) is pending manager approval. "
            "You'll be notified once it's approved."
        )
    return f"Order #{order_id} placed: {names} (${total:.2f})."


def _render_allergen_conflicts(conflicts: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for c in conflicts:
        if "ingredient" in c:
            group = c.get("allergen_group", "an allergen")
            parts.append(f"{c['ingredient']} ({group})")
        else:
            allergens = ", ".join(c.get("matched_allergens", [])) or "an allergen"
            parts.append(f"{c.get('name', 'that item')} ({allergens})")
    return "I can't recommend that — it conflicts with your allergens: " + "; ".join(parts) + "."
