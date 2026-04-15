# Recommendation Agent

**Type:** Reasoning + Ranking | **LLM:** Claude Sonnet (with deterministic fallback) | **Priority:** Core

---

## Role

The Recommendation Agent is the **personalization engine**. It takes the filtered menu items and the user's profile, scores every item for relevance, then uses Claude to generate friendly, context-aware meal suggestions. It operates in two stages: deterministic scoring for a reliable baseline, then LLM reasoning for natural-language presentation.

---

## Capabilities

### 1. Two-Stage Ranking

**Stage 1 — Deterministic Scoring:**
Every menu item gets a numeric score based on weighted signals:

| Signal | Weight | Example |
|---|---|---|
| Current request match | +25 per keyword | User says "pasta" -> items with "pasta" score higher |
| Favorite cuisine | +10 | User loves Thai -> Thai items boosted |
| Preference keywords | +5 | Memory says "loves spicy" -> spicy items boosted |
| Disliked items | -30 | Memory says "dislikes tofu" -> tofu items penalized |
| Budget alignment | +5 / -5 | Cheap items boosted when budget preference exists |
| Healthy category | +5 | Healthy items get a small baseline boost |

**Stage 2 — LLM Presentation:**
Top 5 scored items are sent to Claude with the user's profile and current message. Claude picks the best 3 and explains *why* each is a good match.

### 2. Allergen Conflict Warnings
When the Menu Agent flags that a requested item was removed due to an allergen conflict, the Recommendation Agent:
- Prepends a clear safety warning to the response
- Instructs the LLM to acknowledge the conflict before suggesting alternatives
- Ensures the user understands *why* their request was changed

### 3. Graceful Degradation
Without a Claude API key, falls back to deterministic-only mode: top 3 items listed with scores, category, cuisine, and calorie counts. No LLM, still functional.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Deterministic scoring first | Guarantees a sane baseline — the LLM refines presentation, it doesn't control item selection |
| Current request outweighs stored prefs | If the user asks for pasta, stored "loves Thai food" shouldn't override that. Explicit > implicit |
| Allergen warnings injected into LLM prompt | Claude must *start* its response with the warning — cannot be buried or omitted |
| Score attached to items | Visible in Langfuse traces for debugging ranking issues |

---

## Pipeline Position

```
Memory --> Menu --> [Recommendation Agent] --> (optional) Execution
                          |
                   Stage 1: rank_items()
                          |
                   Stage 2: Claude LLM
                          |
                          v
                   recommendation_text +
                   top 3 recommendations[]
```

**Reads from state:** menu_items, user_profile, constraints, user message, allergen_conflicts
**Writes to state:** recommendations (top 3), recommendation_text (display string)
