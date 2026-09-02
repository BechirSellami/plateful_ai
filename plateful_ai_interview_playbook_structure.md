# Plateful AI — Interview Playbook (Structure)

> Format: internal Architecture Decision Record (ADR), not a README.
> Organizing principle: every section answers "why", not just "what".

---

## 1. Interview Cheat Sheet *(deliberately first — this is the page you re-read before the call)*

- **2-minute pitch** — problem, architecture in one sentence, the one decision that defines the system (hybrid deterministic + LLM)
- **5-minute deep dive script** — planner → router → agent workflow, one compound-request example end to end
- **One-liner per key decision** — memorize these; each maps to a mini-ADR in section 3
- **Likely interviewer questions + prepared answers**
  - Why not a single LLM with a big prompt?
  - Why not an LLM orchestrator (e.g. LangGraph-style dynamic routing)?
  - How do you prevent hallucinated workflows?
  - How does this scale / what breaks first under load?
- **Key numbers** — token cost per turn, p50 latency, routing accuracy from `golden_routing.py`, test count

---

## 2. Architecture & Request Lifecycle *(merged former sections 2–5)*

### 2.1 Business scenario (brief)
Catering workflow: recommendations, ordering, meal planning, preference learning.

### 2.2 High-level architecture (one diagram)
```
User
 ↓
Planner (intent, constraints, compound flags, AND the proposed
         execution plan itself — decides WHAT and proposes HOW)
 ↓
Plan Validator (deterministic — checks the proposal against
                AGENT_CONTRACTS; falls back to compose_plan if invalid)
 ↓
Memory → Menu → Policy → Recommendation → Execution
                  ↑
   (deterministic allergen/safety filtering — outside the LLM,
    checks persisted profile AND the current message)
 ↓
Learning agent (ordered last by contract; NOT yet off the latency
                path on the live route — say this precisely if asked)
 ↓
Response
```
> Note: the Policy agent MUST appear in this diagram — it carries the
> deterministic-safety story that section 3 leans on. It's reachable via
> an LLM-proposed plan today, not yet a default route.

### 2.3 End-to-end lifecycle (one realistic example)
Walk one compound request through the full pipeline:
*"I'm allergic to peanuts and I'd like to order the spicy tofu."*
→ planner output (JSON, including the proposed plan) → Plan Validator
checks it against contracts → memory update + menu filter (profile +
this message) + execution + learning, in that order.

### 2.4 Agent responsibility table (compact)
| Agent | Purpose | Inputs | Outputs | Owns tools? |
|---|---|---|---|---|
| Planner | intent + constraints + compound flags | user msg, context | structured plan | no |
| Memory | preference retrieval/update | plan | preferences | yes (Mem0) |
| Menu | menu grounding | constraints | candidate items | yes |
| Policy | deterministic safety filter | items + allergens | filtered items | yes |
| Recommendation | ranked suggestions | filtered items + prefs | recommendations | yes |
| MealPlan | weekly plan CRUD | plan state | updated plan | yes |
| Execution | order placement | selection | confirmation | yes |
| Learning | preference learning, ordered last by contract (not yet async on the live path) | full turn | memory writes | yes |

---

## 3. Decisions & Trade-offs *(merged former sections 6 + 10 — the spine of the document)*

Each decision uses a **mini-ADR format**:
**Context → Alternatives considered → Decision → Consequences (incl. what it cost you)**

1. **Hybrid architecture** — LLM for reasoning AND plan composition, deterministic code for validation and enforcement
2. **Planner/Plan Validator separation** — planner proposes the full ordered plan; a contract-based validator (`resolve_validated_plan`) checks it before anything runs, falling back to deterministic routing if it fails → prevents hallucinated *or unsafe* workflows without denying the model real planning freedom. (Evolved from an earlier design where planner produced structured output only and a static router composed the workflow — tell that evolution story if there's time.)
3. **Agents own their tools** — orchestrator is tool-agnostic; each agent runs its own Claude tool loop → scalability, encapsulation
4. **Deterministic safety, two layers** — the validator guarantees the allergen-filter step is present; the Menu Agent's own filter guarantees it screens the persisted profile *and* the current message (a same-turn allergy declaration is protected immediately — this was a real bug, found and fixed, not a hypothetical)
5. **Compound request handling** — one turn can trigger a multi-agent workflow the Planner composes itself, including combinations no static routing table was ever written for
6. **Stateful conversation over WebSockets** — meal plans/menu/recs persist across turns; enables "replace Tuesday with pasta" without regeneration; also tells the planner what's already available so it knows when a step is safe to skip
7. **Learning ordered last by contract** — NOT currently async on the live path (known, named gap — the dispatch mechanism exists but isn't wired to the live flow); be precise about this if asked
8. **Agent contracts as a real gate, not just docs** — promoted from warn-mode logging to an enforced pre-execution check; finding and closing a genuine bypass (`execution` accepting a bare `selected_item`) was a prerequisite for that promotion, not an afterthought
9. **Specialized agents vs. one large prompt** — cost: more moving parts; gain: testability, bounded context per agent

> Attach a number to every decision where possible (tokens saved, latency delta,
> routing accuracy). Quantified trade-offs land hardest at Lead/Principal level.

---

## 4. Failure Modes & Production Readiness *(new section — folds in former section 9)*

### 4.1 Failure taxonomy — what breaks and how it's handled
- Planner misclassifies intent → falls back to the default flow; out-of-scope tests
- Planner proposes a contract-invalid or unsafe plan → Plan Validator rejects and substitutes the deterministic fallback (hard gate, not a warning)
- Mem0 unavailable / stale preferences → graceful degradation, system still works
- Claude API down → deterministic fallback paths, system still works
- Tool loop exceeds max iterations → bounded loop, contract enforcement
- WebSocket drop mid-workflow → state recovery strategy
- Compound request partially fails → per-step handling, partial-success semantics

### 4.2 Observability
- Traces, audit snapshots, token usage tracking, structured logging
- Agent contracts as a runtime gate, not just validation — the Plan Validator's accept/reject decision is on the trace too

### 4.3 Testing strategy
- Unit (per-agent, per-toolset, routing, contracts, observability)
- Integration
- Evals: `golden_routing.py` (now scores intent accuracy, raw-plan validity, and executed-plan fidelity as three separate signals, plus a `dynamic` category built specifically to exercise compositions no static flow ever produced), **`safety_redteam.py`** (red-teaming the allergen filter function — lead with this; almost no personal project has it), and **`plan_safety_redteam.py`** (red-teaming the plan-validation layer itself — the exact bypass a dynamic planner could otherwise produce)

### 4.4 Memory architecture
- Mem0, long-term preference storage, retrieval strategy, update flow via Learning agent

---

## 5. Lessons Learned & Roadmap *(former section 11)*

**Shipped since the original version of this playbook** — dynamic workflow composition (Planner proposes the plan, Plan Validator gates it), same-turn allergen protection, and the contract registry promoted from warn-mode to an enforced gate. This is now the strongest "walk me through a decision" story in the project — including a real safety bug found and closed while building it (see Demo_reference.md, Decision 2).

Still open:
- Wire the existing async-dispatch mechanism into the live `learning` step (exists in code, not connected)
- Multi-agent parallel execution — deliberately deferred; today's catalog has one real independent pair (memory/menu), not enough to justify the concurrent-state-write complexity yet
- MCP integration
- Agent-to-agent (A2A) communication
- Human approval workflows
- Cost-based model routing
- Richer evaluation and benchmarking — `golden_routing.py` and the two red-team suites are a start, not the ceiling

---

## Appendix — deliberately de-emphasized
FastAPI, React, SQLAlchemy, Postgres. Mention only if asked; the architecture is the story.
