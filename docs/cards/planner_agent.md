# Planner Agent

**Type:** Orchestration | **LLM:** Claude Sonnet (with keyword fallback) | **Priority:** Core

---

## Role

The Planner Agent is the **brain of the pipeline**. It analyzes every user message and decides which agents need to run, in what order. Unlike a static router, it handles **compound requests** — a single message like *"I love spicy food, what do you recommend?"* triggers both the Learning Agent (save preference) and the Recommendation Agent (suggest meals) in one pass.

---

## Capabilities

### 1. LLM-Driven Planning
Sends the user message + available agent catalog (rendered live from each agent's declared contract — `requires`/`produces`/`post_action` — so the prompt can never drift from what the validator actually checks) to Claude, which returns a structured JSON execution plan:
```json
{"intent": "get_recommendation", "constraints": {"cuisine": "thai"},
 "plan": [{"agent": "memory", "reason": "..."}, {"agent": "menu", "reason": "..."}, ...]}
```

### 1b. The Plan Is Proposed, Not Trusted
The Planner's output is not executed as-is. A **Plan Validator** (`resolve_validated_plan`) checks the proposed plan against every agent's declared contract before anything runs:
- Required inputs must already be produced by an earlier step (or already available this session).
- Post-action agents (`learning`) must run last.
- One rule is safety-critical, not just structural: `execution` can never be satisfied by a bare `constraints.selected_item` — naming an item isn't the same as it having passed the allergen filter. `menu` (or an already-filtered `menu_items`/`recommendations`/`meal_plan`) must precede it.

A plan that fails any check is discarded and replaced with the deterministic `compose_plan` fallback for that intent — the same mechanism used when the LLM itself is unavailable. The Planner has real freedom in how it composes agent sequences; it has zero authority to get an invalid one executed.

### 2. Compound Intent Detection
A single message can contain multiple intents. The planner decomposes them:
- *"I'm vegetarian, recommend something"* -> Learning + Memory + Menu + Recommendation
- *"I'll take the Grilled Chicken Bowl"* -> Execution + Learning
- *"Swap the tofu in my meal plan"* -> Menu + MealPlan

### 3. Keyword Fallback
When the LLM is unavailable or returns an unparseable response, the planner falls back to deterministic keyword matching. This ensures the system **never goes down** even if the API is unreachable.

### 4. Meal Plan Context Awareness
When the user has an active meal plan, the planner injects it into the LLM prompt so swap/submit requests are routed correctly — even when phrased indirectly (*"not a fan of the tofu"*).

### 5. Out-of-Scope Detection
Identifies non-food requests (*"What's the weather?"*) and short-circuits with a helpful redirect message, avoiding unnecessary agent execution.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| LLM with keyword fallback | Best-of-both: nuanced understanding when available, guaranteed uptime when not |
| JSON output format | Structured plans are directly parseable, but never directly *executed* — the Plan Validator gates every proposal first |
| Contract-derived catalog, not hand-written prose | The agent list shown to the LLM is generated from `AGENT_CONTRACTS`, so the dependency info it plans against can't drift from what actually gets validated |
| Markdown fence stripping | Claude sometimes wraps JSON in code fences; pre-parse stripping handles this gracefully |
| Active plan injected in prompt | Without context, the LLM can't distinguish *"swap the tofu"* from a general recommendation request |

---

## Pipeline Position

```
User Message
     |
  [Planner Agent]  <-- First agent, always runs
     |
     +--> intent + constraints + proposed ordered agent plan
     |
  Plan Validator (resolve_validated_plan)
     |
     +--> valid?   --> execute as proposed
     +--> invalid? --> replace with deterministic compose_plan fallback
     |
  Orchestrator executes the (validated) plan sequentially
     |
     +--> Memory --> Menu --> Recommendation --> ...
```

**Reads from state:** user message, active meal plan
**Writes to state:** intent, constraints, execution plan
