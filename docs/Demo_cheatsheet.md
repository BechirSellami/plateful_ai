# Plateful AI — Interview Cheat Sheet

> Last updated: 2026-09-02
>
> Purpose: A rapid refresher before an interview. Read this document in under 10 minutes.

---

# 30-Second Elevator Pitch

Plateful AI is a hybrid multi-agent catering assistant that combines LLM-driven planning with a deterministic safety gate.

Instead of trusting an LLM's execution plan blindly, or hand-writing a routing rule for every scenario, the system separates proposing a plan from validating it:

- The **Planner Agent** extracts structured intent and constraints, and composes the ordered execution plan itself.
- A **Plan Validator** checks that proposal against every agent's declared contract before anything runs, and swaps in a deterministic fallback plan if it fails.
- Specialized agents collaborate by updating a shared `WorkflowState`.
- Preferences are persisted through a dedicated Learning Agent, ordered last in every plan.

The result is a system that's adaptable to new request shapes without a new routing rule for each one, while staying as testable and predictable as a fully deterministic router — because nothing executes without passing the gate.

---

# 2-Minute Walkthrough

1. User sends a request.

2. Planner Agent extracts:
   - Intent
   - Constraints
   - Compound request flag
   - **The ordered execution plan itself** (which agents, in what order)

3. Plan Validator checks the proposed plan against each agent's declared contract (`AGENT_CONTRACTS`). Valid → runs as proposed. Invalid → replaced with the deterministic fallback for that intent (the same one used when the LLM itself is unavailable).

4. Specialized agents execute in sequence by reading from and writing to a shared `WorkflowState`.

5. Learning Agent updates long-term preferences as the last step of the plan.

6. Final response is returned.

---

# Core Design Decisions

## Hybrid Architecture

LLMs perform reasoning **and now plan composition**.

Software validates and enforces safety.

---

## Planner vs Plan Validator

Planner decides **what** the user wants, **and proposes how** to execute it.

Plan Validator decides **whether that proposal is safe and contract-valid to actually run**.

Planner never executes workflows directly — but it does compose them now. The validator is what stands between an LLM-authored plan and the executor; nothing runs on the model's word alone.

> This is the answer to "why not let the LLM own execution order" — the honest answer isn't "we don't," it's "we do, but nothing it proposes runs unchecked."

---

## Shared WorkflowState

Agents never call one another directly.

Instead they exchange information through a shared `WorkflowState`.

Benefits:

- loose coupling
- easier testing
- simpler orchestration
- easier extensibility

---

## Deterministic Safety — two independent layers

**Layer 1 — the Plan Validator** guarantees a filtering step is present in any plan that reaches `execution`. Its contract explicitly refuses to let `execution` proceed on a user-named `selected_item` alone — naming an item isn't the same as it having passed the allergen filter. `menu` (or an already-filtered `menu_items`/`recommendations`/`meal_plan`) must precede it, or the plan is rejected.

**Layer 2 — the Menu Agent's own filter** is deterministic and happens **inside the Menu Agent**, before the Recommendation Agent generates any text. It checks the persisted profile **and scans the current message directly** — so "I'm allergic to shellfish, order me something Asian" is protected on that same turn, not just from the next one onward. Unsafe items never reach the LLM's candidate set.

A `PolicyAgent` exists in the codebase. It's reachable today if the Planner proposes a plan that includes it and the plan passes validation (`policy` requires `recommendations` or `menu_items`) — no static fallback route includes it yet, so describe it as "reachable via LLM-proposed plans, not yet a default path," rather than a pure future extension point.

---

## Agent Autonomy

Each agent owns its own tools and domain logic.

The executor remains unaware of implementation details.

---

## Learning — ordered last, not yet off the critical path

`learning`'s contract marks it `post_action`: the Plan Validator guarantees it never runs before another agent that might still need to act. **Be precise if asked about this**: on the live LLM-planned path, `learning` executes synchronously like any other step — the response is only returned after it completes. A fire-and-forget `asyncio.create_task` dispatch pattern exists in the codebase, but it's wired into an unused legacy static flow, not the planner-driven path that's actually live. Say "bounded and ordered-last, contract-enforced" with confidence; don't claim "async" unless you also mention it's a known, well-scoped gap.

---

## Graceful Degradation

Without Claude: deterministic keyword planning and ranking take over — same fallback the Plan Validator uses for a rejected plan. Without Mem0: memory steps are skipped and personalization degrades.

> The system degrades in capability, not availability — for an unavailable LLM and for an LLM that proposes a bad plan alike.

---

# Example Flow

User:

> "I'm allergic to peanuts and I'd like to order the spicy tofu."

Planner extracts and proposes:

```json
{
  "intent": "confirm_order",
  "constraints": {"selected_item": "spicy tofu", "preference": "allergic to peanuts"},
  "compound_flags": {"has_preference": true},
  "plan": [
    {"agent": "memory", "reason": "check allergies"},
    {"agent": "menu", "reason": "filter safe items before ordering"},
    {"agent": "execution", "reason": "place the order"},
    {"agent": "learning", "reason": "remember the preference"}
  ]
}
```

Plan Validator checks it — `menu` precedes `execution`, `learning` is last, all inputs satisfied — **valid**, runs exactly as proposed:

Memory

↓

Menu (deterministic allergen filter — tofu checked against the peanut allergy, **including the one just stated in this message**)

↓

Execution (order confirmed or safe alternative offered)

↓

Learning (persists the new allergy — last step, same request)

↓

Response

Note: no Recommendation step here. `confirm_order` goes straight to execution; Recommendation only appears in `get_recommendation` flows. Had the Planner instead proposed `[execution]` alone — trying to place the order on `selected_item` with no filtering step — the Plan Validator would reject it and substitute this same sequence.

---

# Why Not One Large Prompt?

Because separating responsibilities provides:

- a testable safety gate independent of what the LLM proposes
- independent testing
- modularity
- maintainability
- easier debugging

---

# Typical Interview Questions

## Why multiple agents?

To isolate responsibilities and reduce prompt complexity.

---

## If the LLM composes the plan, how do you prevent hallucinated or unsafe workflows?

The Plan Validator checks every proposed plan against declared agent contracts before execution — required inputs, ordering rules (post-action agents last), and one safety-critical rule that isn't just structural: `execution` can never proceed on a named item alone, only on a filtered menu / recommendations / existing meal plan. A plan that fails any check is discarded and replaced with a deterministic fallback. The LLM has real freedom in composition; it has zero authority to actually execute something invalid.

---

## Why shared WorkflowState?

It decouples agents from one another while providing a single source of truth for the current request.

---

## Where is safety enforced?

Twice, independently. The Plan Validator guarantees the allergen-filtering step is present in any plan reaching `execution`. The Menu Agent's own deterministic logic guarantees that step actually screens every allergen mentioned — from persisted memory *and* the current message — before any recommendation text is generated. The LLM can explain a recommendation; it never decides whether an allergen is safe, and it can't route around the check either.

---

## Why is learning ordered last, and is it async?

It's contract-enforced to run last (`post_action`) so nothing downstream depends on stale state. It is **not** currently async on the live path — that's an honest, known gap, not something to oversell. The dispatch mechanism for true fire-and-forget execution already exists in the codebase; wiring it into the planner-driven path is a small, well-scoped follow-up.

---

## What would you improve?

- **Wire async dispatch into the live learning step**

   The `asyncio.create_task` fire-and-forget pattern already exists (`run_workflow`'s `step.get("async")` branch) but only on an unused legacy static flow. Wiring it into the planner-driven path would take `learning` off the response-latency path for real.

- **Parallel agent execution**

   Independent agents, such as Memory and Menu retrieval, could execute concurrently rather than sequentially. I looked at this directly: today's agent catalog only has one real independent pair (memory/menu — everything else has a data dependency, is `post_action`, or is a deliberate `side_effect` you want sequenced), so the win is currently small relative to the complexity of auditing concurrent writes to a shared `WorkflowState`. Worth it once the agent catalog grows or a latency profile actually shows it's the bottleneck — not before.

- **MCP Integration**

   Adopting the Model Context Protocol (MCP) would provide a standardized way for agents to discover and interact with external tools and data sources.

- **Agent-to-Agent (A2A) Communication**

   Today, agents collaborate indirectly through a shared WorkflowState. Direct A2A communication would enable more decentralized collaboration at the cost of centralized reasonability — I'd want a clear failure case that shared-state coordination can't handle before taking on that complexity.

- **Cost-Aware Model Routing**

   Not every task requires the most capable or expensive model. A routing layer could select the appropriate model based on task complexity, latency requirements, and cost.

- **Human Approval Workflows**

   Certain actions, such as placing large catering orders, could require explicit user approval before execution — a natural extension of the Policy Agent once it's on a default path.

- **Richer Evaluation Framework**

   `golden_routing.py` now scores three separate signals (intent accuracy, raw-plan validity, executed-plan fidelity) instead of one, plus a `dynamic` case category built specifically to exercise compositions no static flow ever produced. Next: track these over time, and expand adversarial coverage the way `plan_safety_redteam.py` did for the allergen-bypass case specifically.

---

# Shipped: Dynamic Planning + Plan Validator Gate

This used to be the top item in "what I'd improve" — it's now implemented, and it's the strongest story in the project. If asked to walk through a real design decision end to end, this is the one:

1. **The problem**: a static `INTENT_FLOWS` routing table can't serve a request shape nobody wrote a row for, and every new compound behavior meant a new hand-written flag (`has_preference` and friends).
2. **The design**: promote the agent contracts (already shipped, previously warn-mode-only) to the source of truth for a validator that gates LLM-authored plans, instead of just logging inconsistencies.
3. **The catch I found and fixed before shipping it**: the naive version of `execution`'s contract let a plan satisfy its input requirement with `selected_item` alone — a value extracted straight from the user's message, with zero guarantee the allergen filter ever ran. That's a plan-shape that never occurs in the static router (it always runs `menu` first) but is trivially reachable once the LLM composes plans freely. Closed by removing `selected_item` from the sufficient-inputs set — `execution` now only accepts inputs that are provably post-filter, transitively, by construction of their own producing agent's contract.
4. **The test that proves it**: `plan_safety_redteam.py` — a red-team suite in the same spirit as `safety_redteam.py`, but one layer up: instead of red-teaming the filter function, it red-teams the *plan shapes* that would bypass it, as hard assertions with no LLM call required.

> This is a better "tell me about a bug you caught" story than most interview prep, because it's a security-relevant gap in your own design that you found by asking "what does dynamic planning actually let the model do differently" — not one a linter or a user found for you.

---

# Things I'd Emphasize

- Hybrid LLM planning + deterministic validation gate
- Planner composes the plan; the Plan Validator is what makes that safe
- The specific allergen-bypass bug found and closed while building the gate
- Shared WorkflowState instead of agent-to-agent calls
- Deterministic allergen safety, including same-turn declarations
- Compound and genuinely novel request handling
- Graceful degradation (LLM down, or LLM plan invalid — same fallback)
- Modular architecture

---

# Things I Wouldn't Spend Time On

Unless specifically asked:

- FastAPI
- React
- SQLAlchemy
- PostgreSQL
- UI implementation

The architecture and design decisions are the story.

---

# One-Line Summary

> An LLM plans — including composing the agent sequence itself — a deterministic Plan Validator gates every proposal against declared contracts before it runs, and specialized agents collaborate through a shared WorkflowState to deliver safe, stateful, and genuinely adaptable conversational workflows.
