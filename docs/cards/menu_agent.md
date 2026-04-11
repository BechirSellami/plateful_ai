# Menu Agent

**Type:** Deterministic Safety Agent | **LLM:** None | **Priority:** Safety-critical

---

## Role

The Menu Agent is the **data gateway** of the pipeline. It fetches the daily menu catalog and applies hard safety filters before any item reaches the recommendation or meal planning agents. Its core design principle: **allergen filtering is never delegated to an LLM** — it uses deterministic, rule-based logic to guarantee safety.

---

## Capabilities

### 1. Constraint-Based Filtering
Narrows the full menu based on what the user asked for:
- **Budget** — e.g. "under $15" removes items above the threshold
- **Cuisine** — e.g. "Thai food" filters to Thai items only
- **Category** — e.g. "healthy" limits to that menu section
- **Calories** — supports max-calorie caps

### 2. Allergen Safety Filter
Cross-references every menu item's allergen tags against the user's declared allergies (pulled from memory by the Memory Agent upstream):
- Uses **word-boundary matching** to avoid false positives (e.g. "shellfish" allergy does not incorrectly flag "fish")
- Supports 14 common allergens: peanuts, tree nuts, shellfish, shrimp, dairy, milk, eggs, wheat, gluten, soy, fish, sesame
- Parses natural-language memory strings like *"User is allergic to shellfish"* into structured allergen names

### 3. Allergen Conflict Detection
When the user explicitly asks for something that contains an allergen they've declared:
- Detects the conflict (e.g. user asks for *"pad thai with shrimps"* but has a shellfish allergy)
- Flags it on the workflow state so downstream agents can **warn the user** instead of silently substituting

### 4. Availability Filtering
Filters items by time-of-day availability windows (breakfast vs. lunch vs. dinner) when configured.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| No LLM involvement | Allergen safety must be **deterministic and auditable** — an LLM hallucination here could cause real harm |
| Conflict detection is separate from filtering | Filtering removes unsafe items; conflict detection tells the user *why*, preserving trust and transparency |
| Word-boundary regex for allergen extraction | Prevents substring false positives ("shellfish" != "fish") without overcomplicating the parser |

---

## Pipeline Position

```
User Message
     |
  Planner --> Memory Agent --> [Menu Agent] --> Recommendation / Meal Plan Agent
                                    |
                         Filters:   |
                         1. Budget/cuisine/category
                         2. Allergen safety (deterministic)
                         3. Conflict detection
                         4. Time availability
```

**Reads from state:** constraints, user_profile.allergies, user message
**Writes to state:** menu_items (safe, filtered list), allergen_conflicts (if any)

---

## Example Trace

**Input:** User says *"I want pad thai with shrimps"*, user profile has *shellfish* allergy

| Step | Result |
|---|---|
| Fetch menu | 20 items returned |
| Allergen filter | Pad Thai removed (contains shellfish), Shrimp Tacos removed (contains shellfish) |
| Conflict detection | Pad Thai flagged — user asked for it but it was removed |
| Availability filter | 18 safe items passed downstream |

**Output:** 18 safe items + 1 allergen conflict warning for Pad Thai
