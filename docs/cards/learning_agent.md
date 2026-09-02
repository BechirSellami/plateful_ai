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

### 4. Ordered Last, By Contract — But Not Yet Async
The Learning Agent's declared contract marks it `post_action`: the Plan Validator requires it to be the last step in any plan that includes it, so nothing downstream ever depends on stale state.

**Be precise about this if asked**: the original intent was a background task — dispatched via `asyncio.create_task`, off the response path. That mechanism exists in the code (`run_workflow`'s `step.get("async")` branch), but it's only wired into an unused legacy static flow, not the live LLM-planned path. On the live path, `learning` runs synchronously and the response is only returned after it completes. This is a known, named gap — a small, well-scoped follow-up to actually wire the existing dispatch mechanism in — not something currently true.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| No LLM for event extraction | Events are derived from structured state, not free text — deterministic logic is sufficient |
| Embedded preference detection | Users embed preferences casually; missing them means losing valuable personalization data |
| Write to Mem0, not local DB | Mem0 handles deduplication and semantic merging — if the user says "I love Thai" twice, it doesn't create duplicates |
| Contract-enforced terminal position | `post_action=True` guarantees `learning` never runs before an agent that might still need to act — enforced by the Plan Validator, not just convention. (Non-blocking execution is the intended *next* step, not yet wired to the live path — see above.) |

---

## Pipeline Position

```
Execution --> [Learning Agent]  (contract-ordered last; runs synchronously today)
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
