# Meal Plan Agent

**Type:** Planning + Editing | **LLM:** Claude Sonnet (for presentation) | **Priority:** Feature

---

## Role

The Meal Plan Agent generates and manages **5-day weekly meal plans** (Monday–Friday). It picks the best unique item per day based on the user's preferences, supports swapping individual days, and persists the plan across conversation turns so the user can iteratively refine it.

---

## Capabilities

### 1. Plan Generation
Uses the same `rank_items()` scoring as the Recommendation Agent, then picks the top-scored item for each day, removing it from the pool after selection to ensure **no repeats across the week**.

- Respects allergies (allergen-filtered items never appear)
- Respects preferences (scored items prioritize favorites)
- Falls back gracefully when fewer than 5 items exist (cycles from top)

### 2. Day Swap Detection
Detects swap requests through two strategies:

| Strategy | Example | Detection |
|---|---|---|
| Explicit day name | *"Swap Monday for pasta"* | Matches "Monday" in message |
| Item name matching | *"Not a fan of the tofu, swap it"* | Matches "tofu" against current plan entries |

Trigger words: *swap, change, replace, switch, update*

### 3. Intelligent Swap Execution
When swapping a day:
- Excludes items already in the plan (prevents duplicates)
- Fuzzy-matches the requested item by name, keywords, cuisine, or category
- Falls back to the full menu if no match found in the filtered pool
- Records the old item for audit/display purposes

### 4. LLM-Powered Presentation
After generating or swapping, sends the plan to Claude for friendly, personalized commentary explaining *why* each day's pick is a good fit. Falls back to a formatted text table when no LLM is available.

### 5. Session Persistence
The meal plan lives on `state.meal_plan` and is carried forward across WebSocket turns via a `session_meal_plan` dict in the WS handler. This means:
- *"Suggest a meal plan"* -> generates plan
- *"Swap the tofu"* -> modifies the existing plan (not a fresh one)
- *"Submit my meal plan"* -> sends the current plan to the Execution Agent

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Ranked pool with removal | Simple, deterministic variety — no item appears twice without explicit cycling |
| Two-strategy swap detection | Handles both *"swap Monday"* and *"swap the tofu"* without requiring the user to remember day assignments |
| Session-level persistence (not DB) | Meal plans are ephemeral drafts until submitted — no need to persist unsubmitted plans |
| Exclusion of planned items from swap pool | Prevents the system from swapping a disliked item with something already on another day |

---

## Pipeline Position

```
Memory --> Menu --> [Meal Plan Agent]
                         |
                    Generate or Swap?
                    /              \
              Generate            Swap
              rank + pick         detect day + resolve item
              5 unique items      replace single day
                    \              /
                     Claude LLM presentation
                         |
                         v
                    state.meal_plan =
                      Monday: Grilled Chicken Bowl
                      Tuesday: Pad Thai
                      Wednesday: Salmon Poke Bowl
                      Thursday: Mediterranean Grain Bowl
                      Friday: Vegan Buddha Bowl
```

**Reads from state:** menu_items, user_profile, constraints, meal_plan (existing), user message
**Writes to state:** meal_plan, recommendation_text
