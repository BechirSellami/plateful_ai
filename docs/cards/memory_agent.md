# Memory Agent

**Type:** Context Enrichment (Read Path) | **LLM:** None (uses Mem0 Cloud) | **Priority:** Personalization

---

## Role

The Memory Agent is the **read path** of the personalization system. Before the pipeline recommends or filters anything, this agent queries the user's long-term memory to retrieve preferences, allergies, dietary restrictions, and past behavior. It transforms raw memory entries into a structured user profile that downstream agents use for personalization.

---

## Capabilities

### 1. Context-Aware Memory Search
Builds a search query tailored to the current request, not a generic fetch:
- Intent-aware: *"User wants to get_recommendation"*
- Constraint-aware: includes budget, dietary, and cuisine constraints in the query
- Falls back to *"food preferences and dietary restrictions"* when no specific context exists

### 2. Profile Construction
Parses natural-language memory entries from Mem0 into structured categories:

| Category | Signal Words | Example Memory |
|---|---|---|
| Allergies | *allerg*, *intoleran* | "User is allergic to shellfish" |
| Dietary restrictions | *vegan*, *vegetarian*, *halal*, *gluten* | "User follows a vegetarian diet" |
| Disliked items | *avoids*, *dislikes*, *hates* | "User dislikes tofu" |
| Preferences | *prefers*, *likes*, *loves*, *enjoys* | "User loves spicy food" |
| Budget | *budget*, *under $*, *cheap* | "User prefers meals under $15" |

### 3. Raw Memory Passthrough
The full raw memory list is preserved on the profile alongside the structured fields, giving downstream agents (especially the LLM-powered ones) access to nuanced context that doesn't fit neatly into categories.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Mem0 Cloud, not local DB | Mem0 handles embedding, deduplication, and semantic search — avoids reinventing a vector store |
| Keyword-based classification | Memory categorization uses simple keyword matching, not LLM — fast and predictable |
| Optional agent (graceful degradation) | When Mem0 is not configured, the agent is simply not registered; the pipeline runs without personalization |

---

## Pipeline Position

```
Planner --> [Memory Agent] --> Menu Agent --> Recommendation / MealPlan
                |
                v
         user_profile:
           preferences: ["loves spicy food"]
           allergies: ["allergic to shellfish"]
           dietary_restrictions: ["vegetarian"]
           favorite_cuisines: ["Thai", "Italian"]
           disliked_items: ["tofu"]
           budget_preference: "under $15"
```

**Reads from state:** user_id, intent, constraints
**Writes to state:** user_profile (structured profile + raw memories)
