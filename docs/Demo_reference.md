# Plateful AI — Interview Reference

> Design-decision playbook for explaining Plateful AI in interviews.
>
> Use this document to answer **why the system was designed this way**, not merely what each component does.

---

## 1. How to position the project

### 30-second summary

Plateful AI is a multi-agent catering assistant for workplace meal recommendations, ordering, weekly meal planning, and preference learning. The core design is a **hybrid LLM planning + deterministic validation architecture**: the LLM interprets the user request *and* composes the execution plan itself, while deterministic code checks that plan against declared agent contracts before anything runs.

The important point is not that the project has several agents. The important point is that each agent has a bounded responsibility, updates a shared `WorkflowState`, and only ever runs as part of a plan that's passed a deterministic safety and correctness gate — never on the model's word alone.

### 2-minute pitch

Plateful AI handles realistic catering requests such as:

> “I’m allergic to peanuts. Can you recommend something spicy?”

That single message contains both a safety-relevant preference and a recommendation request. The Planner extracts the intent, constraints, and compound flags — and proposes the ordered agent sequence itself. A Plan Validator checks that proposal against each agent's declared contract (required inputs, output ordering, one safety-critical rule about the allergen filter) before anything executes; an invalid plan is discarded and replaced with a deterministic fallback. The executor then runs specialized agents that read and update a shared `WorkflowState`: memory retrieval, menu lookup, deterministic allergen filtering, recommendation generation, order execution, and preference learning.

The design deliberately avoids letting the LLM's plan run *unchecked* — not by denying it authority over execution order, but by gating that authority with a contract-based validator the LLM can't talk its way around.

### One-sentence architectural thesis

> Plateful AI lets an LLM plan — including composing the agent sequence itself — but a deterministic Plan Validator, not the model's judgment, decides what's actually safe and contract-valid to execute.

---

## 2. What to emphasize in interviews

### The strong signals

| Signal | Why it matters |
|---|---|
| Hybrid LLM planning + deterministic gate | Shows engineering judgment beyond “LLM does everything” *or* “LLM does nothing but classify.” |
| Planner/Plan Validator separation | The LLM composes the plan; contracts decide whether it runs. Prevents hallucinated or unsafe workflows without denying the model real planning freedom. |
| Shared `WorkflowState` | Makes agent coordination explicit without direct agent-to-agent calls. |
| Deterministic allergen filtering, incl. same-turn | Keeps safety outside model judgment — and outside constraint-extraction fidelity, since it scans the message directly. |
| Compound and novel request handling | Handles realistic, even unseen-shape, user turns instead of toy single-intent prompts. |
| Stateful WebSocket flow | Supports follow-ups like “swap Tuesday for pasta.” |
| Graceful degradation | System remains usable without Claude or Mem0, or when the LLM's plan is invalid. |
| Observability and audit snapshots | Demonstrates production-minded debugging and traceability. |
| Agent contracts as a real gate, not just docs | The exact mechanism that makes dynamic planning safe — and the one I found a bypass in before shipping it. |

### What not to overemphasize

Do not lead with FastAPI, React, SQLAlchemy, or Postgres. They are useful implementation details, but the interview story is the architecture: planning, routing, workflow state, safety, memory, and trade-offs.

---

## 3. Design decisions and trade-offs

Each section follows a mini-ADR format:

> **Context → Alternatives considered → Decision → Consequences**

---

## Decision 1 — Hybrid LLM + deterministic workflow control

### Context

The system needs to understand flexible natural language while also performing concrete actions: retrieve menus, filter unsafe items, recommend dishes, place orders, and update memory.

A pure LLM chatbot can produce fluent responses, but it does not provide enough control over execution, safety, testing, or failure handling.

### Alternatives considered

| Option | Why not |
|---|---|
| Single large prompt | Simple, but hard to test, hard to observe, and prone to hidden workflow drift. |
| LLM as full orchestrator | Flexible, but gives the model too much authority over execution order. |
| Fully deterministic chatbot | Predictable, but weak at natural language understanding and compound requests. |

### Decision

Use the LLM for intent extraction, constraint extraction, and — this is the part that evolved, see Decision 2 — plan composition itself. Deterministic code validates and executes the workflow, rather than composing it from scratch.

### Consequences

**Benefits**

- Workflow behavior is testable, because nothing runs without passing a contract check first.
- Safety and execution rules are explicit and enforced independently of what the LLM proposes.
- LLM failures — or LLM plans that fail validation — fall back to keyword planning / deterministic routing.
- The system is easier to explain and debug.

**Costs**

- More code than a single-prompt prototype.
- Requires maintaining declarative contracts per agent (`AGENT_CONTRACTS`) instead of a routing table.
- Compound flows still benefit from explicit signals such as `has_preference`, even though the LLM now decides how to act on them.

### Interview soundbite

> I treated the LLM as a reasoning *and planning* component, but never as the sole authority over what actually executes.

---

## Decision 2 — Planner proposes the full plan; a Plan Validator gates it

> **This decision superseded an earlier one.** The system originally had the Planner extract structure only (intent, constraints, compound flags) while a deterministic router composed the workflow from a static `INTENT_FLOWS` table. That table still exists — it's now the fallback, not the primary path. Below is the current decision; the "what changed and why" is worth telling as its own story if asked, since it's the strongest design narrative in the project.

### Context

The Planner needs to understand messages like:

> “I love tofu. I’ll have it today.”

This contains both a preference signal and an order confirmation. The original design solved this with a primary intent plus boolean compound flags (`has_preference`) that a static router mapped to workflow steps — but every new compound behavior needed a new flag and a new routing-table entry. That doesn't scale to request shapes nobody anticipated, which is the actual promise of using an LLM here in the first place.

### Alternatives considered

| Option | Why not |
|---|---|
| Planner extracts structure only; static router composes (the original design) | Correct but doesn't scale — every new compound behavior needs a new flag and a new hand-written routing entry. Can't serve a request shape nobody wrote a row for. |
| Planner returns an arbitrary agent sequence, trusted as-is | Too much freedom with no check; the LLM could produce an invalid or unsafe workflow and nothing would catch it. |
| Planner proposes the full plan; a contract-based Plan Validator gates it before execution | Real composition freedom, bounded by a hard, testable gate — not by asking the model to remember the rules. |

### Decision

The Planner returns the plan directly:

```json
{
  "intent": "confirm_order",
  "constraints": {
    "selected_item": "tofu",
    "preference": "likes tofu"
  },
  "compound_flags": {
    "has_preference": true
  },
  "plan": [
    {"agent": "memory", "reason": "check allergies"},
    {"agent": "menu", "reason": "filter safe items before ordering"},
    {"agent": "execution", "reason": "place the order"},
    {"agent": "learning", "reason": "remember the preference"}
  ]
}
```

`resolve_validated_plan` (the Plan Validator) checks it against `AGENT_CONTRACTS` — each step's required inputs must already be produced by an earlier step, post-action agents (`learning`) must run last, and `execution` specifically can never be satisfied by a bare `selected_item` (only by a filtered `menu_items`, `recommendations`, or an existing `meal_plan` — all of which are, by construction of their own contracts, guaranteed to have already passed the allergen filter). A plan that fails any check is discarded and replaced by the deterministic `compose_plan` fallback — the same mechanism that already existed for LLM outages.

### The bug this design change surfaced

Building the validator surfaced a real gap, not a hypothetical one: the first version of `execution`'s contract accepted `selected_item` alone as sufficient. A static router never exploits that (it always runs `menu` first), but a plan the LLM composes freely absolutely could — e.g. proposing `[execution]` directly for "I'll take the Pad Thai," skipping the allergen filter entirely. Fixed by removing `selected_item` from the sufficient-inputs set; a red-team suite (`plan_safety_redteam.py`) now asserts that exact bypass shape is always rejected, as a hard, LLM-free assertion.

### Consequences

**Benefits**

- The LLM can compose agent sequences no one wrote a routing rule for — measured directly by a `dynamic` category in `golden_routing.py` built from compositions no static flow produces.
- Nothing executes without passing the same contract check, whether the plan came from the LLM or the deterministic fallback.
- Keeps LLM and keyword-fallback modes aligned: an LLM plan that fails validation degrades to exactly the fallback the keyword path would have produced anyway.

**Costs**

- Contracts must correctly encode every safety-relevant ordering rule, not just data dependencies — the `execution`/`selected_item` bug above is exactly what happens when they don't, initially.
- More moving parts than a single routing table: planner prompt, contract registry, validator, and fallback all need to stay in sync.
- `golden_routing.py`'s scoring had to split into three signals (intent accuracy, raw-plan validity, executed-plan fidelity) instead of one, since a plan mismatch is no longer automatically a bug — it might be a legitimate alternate ordering.

### Interview soundbite

> The Planner decides what the user means and proposes how to act on it. The Plan Validator decides whether that proposal is actually allowed to run — and I found a real safety gap in my own first draft of that gate before it shipped, which is a better story than claiming it was correct from the start.

---

## Decision 3 — Agents coordinate through shared `WorkflowState`, not direct calls

### Context

A common misconception in multi-agent systems is that agents must talk to each other directly. In this project, the workflow runner executes each agent step in order. Each agent reads from and writes to the same `WorkflowState`.

### Alternatives considered

| Option | Why not |
|---|---|
| Direct agent-to-agent calls | Harder to trace, test, and reason about. Coupling grows quickly. |
| Central orchestrator owns all logic | Agents become thin wrappers; orchestration becomes bloated. |
| Shared state + ordered execution | Clear boundaries with inspectable state transitions. |

### Decision

Use `WorkflowState` as the coordination mechanism. Agents do not call each other. They update state fields such as `user_profile`, `menu_items`, `recommendations`, `meal_plan`, `order`, and `last_result`.

### Consequences

**Benefits**

- Every step has a clear before/after state.
- Tracing and audit snapshots are easier.
- Agents remain independent execution units.
- The workflow can be reasoned about like a state machine.

**Costs**

- The state object can grow over time.
- Requires discipline around which agent owns which fields.
- Hidden dependencies can emerge if agents rely on fields implicitly.

### Interview soundbite

> This is not agents chatting with each other. It is deterministic workflow execution over a shared state object.

---

## Decision 4 — Specialized agents instead of one large prompt

### Context

The application spans several responsibilities: memory, menu retrieval, safety filtering, recommendation, meal planning, execution, and learning. Putting all of that into one prompt would be easy initially but difficult to maintain.

### Alternatives considered

| Option | Why not |
|---|---|
| One large prompt | Fast to prototype, but hard to test and extend. |
| Many free-form agents | Flexible, but risks chaotic execution. |
| Specialized agents in a deterministic workflow | Modular while retaining control. |

### Decision

Use purpose-built agents with bounded responsibilities:

| Agent | Responsibility |
|---|---|
| Planner | Intent, constraints, compound flags |
| Memory | User profile, preferences, allergies, history |
| Menu | Menu retrieval and deterministic filtering |
| Recommendation | Ranking and user-facing suggestion text |
| MealPlan | Weekly plan creation and edits |
| Execution | Order confirmation and submission |
| Learning | Preference and order memory writes |

### Consequences

**Benefits**

- Easier unit testing.
- Smaller contexts per agent.
- Clear ownership of tools and state updates.
- New capabilities can be added without rewriting the whole assistant.

**Costs**

- More moving parts.
- More contracts and integration tests needed.
- Requires clear orchestration to avoid over-engineering.

### Interview soundbite

> I used multiple agents for separation of concerns, not because “multi-agent” is fashionable.

---

## Decision 5 — Deterministic allergen safety inside the Menu Agent

### Context

Meal recommendation has a safety dimension. If a user says they are allergic to peanuts or shellfish, unsafe items must not be recommended.

### Important implementation note

A `PolicyAgent` exists in the codebase. It's reachable if the Planner proposes a plan that includes it and the plan passes contract validation — no static fallback route includes it, so it's an LLM-reachable extension point, not yet a default path. The active safety path today is deterministic allergen filtering inside the `MenuAgent`, backed by the Plan Validator guaranteeing that filtering step is present at all.

### Alternatives considered

| Option | Why not |
|---|---|
| Ask the LLM whether an item is safe | Unsafe; model judgment should not be the final safety layer. |
| Rely only on recommendation prompt instructions | Too easy for unsafe items to leak through. |
| Filter candidates before recommendation, sourced from persisted profile only | Safer and testable, but misses a same-turn declaration — see the real bug below. |
| Filter candidates before recommendation, sourced from persisted profile **and the current message** | Same testability, closes the same-turn gap. |

### Decision

Apply deterministic allergen filtering during menu retrieval, before the Recommendation Agent receives candidate items — checking both the persisted profile and a direct scan of the current message.

### A real bug this caught, live

While demoing, "I'm allergic to shellfish and want to order asian today" returned an empty result — traced to two independent bugs, not one: (1) `cuisine: "asian"` matched nothing because the menu only tags specific cuisines (`thai`, `japanese`, ...), not the umbrella term — fixed with a cuisine-group synonym map; (2) more seriously, `user_allergens=[]` at filter time, because the filter only ever read `state.user_profile["allergies"]` — populated from *persisted* Mem0 data — and never looked at the allergy declared in that same message. A first-time "I'm allergic to X, order me Y" was not actually protected until the *next* turn. It didn't leak an unsafe item only because bug (1) already zeroed the candidate set first. Fixed by having the Menu Agent scan the current message directly, independent of whether the planner also managed to extract it into `constraints.preference`.

### Consequences

**Benefits**

- Unsafe items are removed before the LLM generates recommendations.
- Allergy conflicts can be surfaced explicitly to the user.
- Safety behavior can be tested without relying on model outputs.
- Protection is immediate — a same-turn declaration doesn't need to round-trip through memory persistence first.

**Costs**

- Requires structured menu metadata.
- Safety quality depends on allergen data completeness.
- The Policy Agent story must be explained carefully: it's LLM-reachable, not yet a default path.
- Simple keyword scanning over-blocks on negation ("I'm NOT allergic to peanuts" still matches "peanuts") — a conservative failure mode consistent with the project's existing "blocking is the safe default" stance, but worth naming if asked.

### Interview soundbite

> The model can explain recommendations, but it does not decide whether an allergen is safe — and I found and fixed a real case where the filter existed but wasn't actually wired to the message that mattered.

---

## Decision 6 — Compound request handling through flags

### Context

Real users often combine requests:

- “I’m vegetarian. What should I order?”
- “I love spicy food. I’ll have the tofu.”
- “I don’t eat shellfish, but recommend something Asian.”

A single-intent classifier would miss part of the request.

### Alternatives considered

| Option | Why not |
|---|---|
| Force the user into multiple turns | Poor UX. |
| Let the LLM create arbitrary multi-step plans, untrusted | Flexible but uncontrolled — this is what Decision 2 does now, *with* the Plan Validator gate making "harder to control" no longer true. |
| Primary intent + compound flags, deterministic router composes | The original design — captured multi-action turns but needed a new flag and routing entry per new behavior. |

### Decision

Represent the main request as one primary intent plus compound flags such as `has_preference` — still true — but the Planner now also decides directly what to do about them in its proposed plan, rather than a router applying a fixed rule per flag.

Example:

```json
{
  "intent": "get_recommendation",
  "constraints": {
    "preference": "peanut allergy",
    "food_keywords": ["spicy"]
  },
  "compound_flags": {
    "has_preference": true
  },
  "plan": [
    {"agent": "memory", "reason": "check allergies"},
    {"agent": "menu", "reason": "fetch safe items"},
    {"agent": "recommendation", "reason": "suggest"},
    {"agent": "learning", "reason": "persist the new allergy"}
  ]
}
```

`compound_flags` still matters — it's a documented signal in the planner prompt and it's what the deterministic `compose_plan` fallback keys off when the LLM path isn't used — but on the live path the Planner acts on it directly by including `learning` in its own proposed plan, rather than a router appending it after the fact.

### Consequences

**Benefits**

- One user turn can trigger multiple system behaviors, including combinations no fixed flag/router-rule pairing ever anticipated.
- The Plan Validator still enforces the structural rule that matters (`learning` last), so this isn't "deterministic became free-form" — it's "the rule moved from a routing table to a contract."
- The implementation is testable with routing evals — now scored on three signals (intent, raw-plan validity, executed-plan fidelity) instead of one, since `golden_routing.py` had to be reworked alongside this change.

**Costs**

- Flags must still be carefully defined and documented in the planner prompt.
- A miss here is now genuinely ambiguous between a classification error and a planning error — the eval rework exists specifically to keep those distinguishable.

### Interview soundbite

> I modeled compound requests explicitly instead of pretending every message has only one intent — and then let the model act on that signal directly instead of hard-coding every combination into a router.

---

## Decision 7 — Stateful conversations over WebSockets

### Context

Meal planning and ordering are naturally multi-turn. A user might ask for a weekly plan, then say:

> “Swap Tuesday for pasta.”

That only works if the session remembers the active plan.

### Alternatives considered

| Option | Why not |
|---|---|
| Stateless request/response API only | Follow-ups lose context. |
| Store everything only in long-term memory | Too heavy for short-lived session state. |
| WebSocket session state + long-term memory | Supports real-time UX and persistent preferences. |

### Decision

Use WebSocket session state to carry active meal plans, menus, recommendations, and selected items across turns. Use memory for longer-term preferences and history.

### Consequences

**Benefits**

- Natural follow-up behavior.
- Meal plan edits can be incremental.
- The system avoids regenerating everything on every turn.

**Costs**

- Session recovery needs thought if the connection drops.
- Requires clear boundary between session state and long-term memory.

### Interview soundbite

> I separated conversational working memory from long-term user memory.

---

## Decision 8 — Learning as a separate agent

### Context

The system should learn from preferences, allergies, accepted recommendations, and submitted orders. But learning should not make the user-facing path slow or brittle.

### Alternatives considered

| Option | Why not |
|---|---|
| Update memory inside every agent | Duplicates logic and spreads memory writes everywhere. |
| Block every response on memory persistence | Adds latency and increases failure surface. |
| Dedicated Learning Agent | Centralizes memory writes and can run after the main outcome. |

### Decision

Use a Learning Agent responsible for writing preferences and order events back to memory. Its contract marks it `post_action`, so the Plan Validator guarantees it's ordered last in any plan that includes it.

### Honest status check

The original intent was fire-and-forget: dispatch `learning` as an `asyncio.create_task` off the response path. That mechanism exists in the code (`run_workflow`'s `step.get("async")` branch) but is only wired into an unused legacy static flow — **on the live LLM-planned path, `learning` runs synchronously and the response waits for it to finish.** This is a real, known gap, not a design decision to defend. If asked "is learning async," the accurate answer is "it's contract-enforced to run last; making it non-blocking on the live path is a small, well-scoped follow-up, not yet done."

### Consequences

**Benefits**

- Preference learning is centralized.
- The Plan Validator enforces its position in the plan, not just convention.
- Memory failures can be isolated.

**Costs**

- Requires defining what signals are worth saving.
- Currently *does* add to response latency on the live path — the async dispatch pattern needs to be wired into the planner-driven flow to actually deliver the original latency benefit.

### Interview soundbite

> Learning is architecturally isolated and contract-ordered last — whether it's off the latency path is a separate, currently open question, and I'd rather say that plainly than oversell it.

---

## Decision 9 — Graceful degradation

### Context

Personal projects often fail completely if an external AI service is unavailable. This project was designed to remain usable without Claude or Mem0.

### Alternatives considered

| Option | Why not |
|---|---|
| Fail fast when Claude/Mem0 is missing | Bad demo reliability and poor production posture. |
| Mock everything | Not representative of real runtime. |
| Deterministic fallbacks | Keeps the app usable with reduced intelligence. |

### Decision

Support deterministic keyword planning and scoring when Claude is unavailable. Skip memory-related steps when memory is not configured.

### Consequences

**Benefits**

- Better demo reliability.
- Easier local development.
- More production-minded failure handling.

**Costs**

- Fallback quality is lower.
- Need tests to ensure fallback and LLM paths stay aligned.

### Interview soundbite

> The system degrades in capability, not availability.

---

## Decision 10 — Observability, contracts, and audit snapshots

### Context

Multi-step AI systems are hard to debug without visibility into planner output, agent inputs, agent outputs, and state transitions.

### Alternatives considered

| Option | Why not |
|---|---|
| Log only final response | Not enough to debug routing or agent behavior. |
| Log every raw object | Noisy and potentially unsafe. |
| Structured trace spans + snapshots | Gives useful inspection points with bounded payloads. |

### Decision

Capture structured inputs/outputs for planner and agent steps, track token usage where available, and optionally persist audit snapshots after each step. Contract validation started as warn-mode logging only — observable but non-blocking — and has since been promoted to a real gate (`resolve_validated_plan`) for the live LLM-planned path: an invalid plan is rejected and replaced, not just logged. `run_workflow` keeps a warn-mode check underneath as defense-in-depth for any other caller that builds a flow_def some other way.

### Consequences

**Benefits**

- Easier debugging of planner mistakes.
- Better visibility into state transitions, including the Plan Validator's own accept/reject decision on the trace.
- More credible production-readiness story — "we log inconsistencies" became "we block on them," which is the actual V2 item the project called out for itself.

**Costs**

- More instrumentation code.
- Must avoid logging sensitive user data unnecessarily.
- Promoting warn-mode to a hard gate meant finding and closing the contract gap described in Decision 2 first — enforcing a check before it's actually correct would have been worse than not enforcing it.

### Interview soundbite

> Contract validation didn't start as a safety gate — it started as a way to see planner mistakes without breaking live requests. Promoting it to an enforced gate was a deliberate, sequenced step: fix what the gate would block first, then flip it from warn to enforce.

---

## 4. Likely interviewer questions

### Why not just use one LLM with a big prompt?

Because the system needs reliable workflow execution, safety filtering, memory updates, and order submission. A single prompt is easier to prototype but harder to test, observe, and constrain. I used the LLM for language understanding and recommendation text, while deterministic code owns execution.

### If the LLM composes the agent sequence, what stops it from producing something unsafe or invalid?

A Plan Validator (`resolve_validated_plan`) checks every proposed plan against each agent's declared contract before execution — required inputs already produced, post-action agents last, and `execution` specifically can never proceed on a bare user-named item, only on something that's provably passed the allergen filter. A plan that fails any check is discarded and replaced with the deterministic fallback for that intent. The Planner has real freedom in composition; it has zero authority to run something invalid.

### Do agents call each other?

No. The executor runs an ordered, validated plan. Each agent reads and writes a shared `WorkflowState`. Coordination happens through state transitions, not direct agent-to-agent messaging.

### Where is safety enforced?

Twice, independently. The Plan Validator guarantees the allergen-filtering step is present in any plan reaching `execution`. The Menu Agent's own deterministic filter guarantees that step actually screens every allergen mentioned — from persisted memory *and* the current message — before the Recommendation Agent generates text. A Policy Agent exists as an LLM-reachable extension point, but it's not on any default fallback path.

### What happens if Claude is unavailable?

The system falls back to deterministic keyword planning and `compose_plan` routing. Quality is lower, but the product remains usable. The same fallback also covers an LLM that's available but proposes an invalid plan.

### What happens if Mem0 is unavailable?

Memory-related personalization degrades, but the system can still retrieve menus and make recommendations without long-term preferences.

### What breaks first at scale?

Likely bottlenecks include LLM latency/cost, database contention around order and audit writes, and WebSocket session management. `learning` currently runs synchronously on the response path too — a known, named gap, not yet fixed. The architecture helps because workflows are explicit and individual steps can be instrumented, cached, parallelized, or replaced.

### What would you improve next?

Wire the existing async-dispatch mechanism into the live learning step (it exists, just isn't connected), richer evals building on the `dynamic` category and repair/fallback-rate tracking already added to `golden_routing.py`, parallel execution once there's a real independent pair worth it or a latency profile justifying it, better session recovery, cost-based model routing, and a more complete policy layer for business rules beyond allergens.

---

## 5. Roadmap

| Improvement | Status |
|---|---|
| LLM-composed plans + contract-based Plan Validator gate | **Shipped.** Was the top "what I'd improve" item; see Decision 2. |
| Same-turn allergen protection (not just persisted profile) | **Shipped** — found and fixed via a real demo bug, not speculatively. |
| Stronger workflow contracts (warn-mode → enforced gate) | **Shipped** for the live LLM-planned path; `run_workflow`'s own check stays warn-mode as a secondary net for other callers. |
| Async dispatch for `learning` | **Not done.** The mechanism exists in code; it's wired to an unused legacy flow, not the live path. Small, well-scoped. |
| Parallelize independent steps | **Deliberately deferred.** Today's agent catalog has exactly one real independent pair (memory/menu); the complexity of auditing concurrent `WorkflowState` writes isn't worth it yet. |
| More complete policy layer | Open. `policy` is LLM-reachable today but not on any default path; extend into budget, approvals, corporate rules. |
| Richer routing evals | Partially shipped — `golden_routing.py` now scores plan validity and fallback rate, not just intent/exact-match; still needs to run over a larger case set with the real LLM tracked over time. |
| Cost-based model routing | Open. |
| Better state ownership | Open. Define exactly which agent owns each `WorkflowState` field. |
| Session recovery | Open. Handle WebSocket drops and resumable workflows more robustly. |
| Human approval workflows | Open. Natural extension of the Policy Agent once it's on a default path. |

---

## 6. Final interview framing

The project should be framed as a demonstration of applied AI engineering judgment:

- You did not build a chatbot; you built a controlled workflow system — and then let the LLM own more of the workflow once you had a way to check it, not before.
- You did not let agents freely call each other; you coordinated them through state.
- You did not rely on the LLM for safety; you filtered deterministically before generation, twice over — plan-level and message-level.
- You did not optimize only for a demo; you added fallback behavior, traces, tests, contracts, and a red-team suite for the plan-validation layer itself, not just the filter function.
- You found a real bug live (same-turn allergen gap, cuisine-matching gap) and fixed both with tests, rather than only describing the design.

The strongest line to remember:

> This project is about using LLMs inside a reliable software architecture — and as the architecture matured, that meant giving the LLM more real authority (composing the plan itself), not less, because the safety mechanism moved from "don't let it decide" to "let it decide, but verify before it runs."
