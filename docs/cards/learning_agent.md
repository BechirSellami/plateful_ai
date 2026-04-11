# Learning Agent

**Type:** Memory Persistence (Write Path) | **LLM:** None (uses Mem0 Cloud) | **Priority:** Personalization

---

## Role

The Learning Agent is the **write path** of the personalization system — the counterpart to the Memory Agent. After each interaction, it distills what happened into memorable facts and saves them to Mem0. This is how the system **gets smarter over time**: preferences declared today inform recommendations tomorrow.

---

## Capabilities

### 1. Event Collection
Scans the workflow state to find learning-worthy events:

| Event Type | Trigger | What's Learned |
|---|---|---|
| `preference_declared` | User says *"I love spicy food"* or *"I'm vegetarian"* | The stated preference or restriction |
| `allergy_declared` | Dietary constraint extracted from message | Specific allergy or dietary need |
| `order_placed` | Order successfully submitted | Which item was chosen and at what price |
| `suggestion_accepted` | Ordered item matches a recommendation | Implicit confirmation that the suggestion was good |

### 2. Embedded Preference Detection
Detects preferences even in **compound messages** where the primary intent is something else:
- *"I love tofu, what do you recommend?"* -> intent is `get_recommendation`, but the preference *"loves tofu"* is still captured
- Uses `has_preference_signal()` to scan for signal words: *love, like, prefer, allergic, avoid, hate, vegetarian, vegan...*

### 3. Session Summary
Consolidates all collected events into a natural-language summary that Mem0 can store:
- Deduplicates redundant events
- Formats into a message structure Mem0 expects
- Tags with user ID for personalized retrieval later

### 4. Async Execution
In the full workflow definition, the Learning Agent runs as a **background task** — it doesn't block the response to the user. Preferences are saved after the user already sees their recommendation or order confirmation.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| No LLM for event extraction | Events are derived from structured state, not free text — deterministic logic is sufficient |
| Embedded preference detection | Users embed preferences casually; missing them means losing valuable personalization data |
| Write to Mem0, not local DB | Mem0 handles deduplication and semantic merging — if the user says "I love Thai" twice, it doesn't create duplicates |
| Background execution | Learning never delays the user's response — personalization is a side effect, not a blocker |

---

## Pipeline Position

```
Execution --> [Learning Agent]  (often runs async/background)
                   |
              Collect events from state:
                - preferences declared?
                - order placed?
                - suggestion accepted?
                   |
              Summarize + write to Mem0
                   |
                   v
              Mem0 Cloud (long-term memory)
                   |
              Retrieved by Memory Agent
              in future sessions
```

**Reads from state:** intent, constraints, user message, order, recommendations
**Writes to state:** last_result (learning summary)
**Side effect:** Writes memories to Mem0 Cloud
