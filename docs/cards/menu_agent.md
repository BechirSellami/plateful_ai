# Menu Agent

**Type:** Deterministic Safety Agent | **LLM:** None | **Priority:** Safety-critical

---

## Role

The Menu Agent is the **data gateway** of the pipeline. It fetches the daily menu catalog and applies hard safety filters before any item reaches the recommendation or meal planning agents. Its core design principle: **allergen filtering is never delegated to an LLM** — it uses deterministic, rule-based logic to guarantee safety.

This is one of two independent safety layers. The Plan Validator (see the Planner Agent card) guarantees a step like this one is *present* in any plan reaching `execution` — its contract refuses to let `execution` proceed on a bare `selected_item` alone. This agent is the other half: it guarantees that, once it runs, it actually screens every allergen the user has mentioned so far, this message included.

---

## Capabilities

### 1. Constraint-Based Filtering
Narrows the full menu based on what the user asked for:
- **Budget** — e.g. "under $15" removes items above the threshold
- **Cuisine** — e.g. "Thai food" filters to Thai items only. Umbrella/regional terms are also understood via a synonym map (`CUISINE_GROUPS`) — e.g. "asian" matches `thai`/`chinese`/`japanese`/`indian`/... even though no item is literally tagged "asian". (Found live: a request for "asian" food returned zero items before this existed — no seed item carries that exact tag.)
- **Category** — e.g. "healthy" limits to that menu section
- **Calories** — supports max-calorie caps

### 2. Allergen Safety Filter
Cross-references every menu item's allergen tags against the user's declared allergies from **two sources, merged**:
- The persisted profile (pulled from memory by the Memory Agent upstream, from prior turns)
- **The current message, scanned directly** — so a first-time "I'm allergic to shellfish, order me something Asian" is protected on *this* turn, not only from the next one once Memory/Learning catch up. This closes a real gap: the filter used to read persisted profile data only, so a same-turn declaration had zero effect on that turn's filtering — found via a live demo trace, not a hypothetical.
- Uses **word-boundary matching** to avoid false positives (e.g. "shellfish" allergy does not incorrectly flag "fish")
- Supports 14 common allergens: peanuts, tree nuts, shellfish, shrimp, dairy, milk, eggs, wheat, gluten, soy, fish, sesame
- Parses natural-language memory strings like *"User is allergic to shellfish"* into structured allergen names — the same extraction is applied to the raw message text, not just memory strings

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
| Scan the current message, not just persisted profile | Relying on the Planner to have extracted the allergy into `constraints.preference`, or on Memory to already have it from a prior turn, both leave a same-turn declaration unprotected. Scanning the message directly is the deterministic, LLM-independent path |
| Conflict detection is separate from filtering | Filtering removes unsafe items; conflict detection tells the user *why*, preserving trust and transparency |
| Word-boundary regex for allergen extraction | Prevents substring false positives ("shellfish" != "fish") without overcomplicating the parser |
| Cuisine synonym groups for umbrella terms | Users say "asian" / "european", not the specific tag a menu item carries; exact-match-only silently returned zero results |

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
