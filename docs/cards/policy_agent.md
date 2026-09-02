# Policy Agent

**Type:** Guardrail / Validation | **LLM:** None | **Priority:** Compliance

---

## Role

The Policy Agent is the **compliance guardrail** of the pipeline. Before any order is placed, it validates the request against configurable business rules — budget caps, per-order limits, and approval thresholds. It decides whether an order can proceed automatically, needs manager approval, or should be blocked entirely.

**Reachability note:** no default or fallback route (`compose_plan`/`INTENT_FLOWS`) includes this agent today. It only runs if the Planner proposes a plan that includes it *and* that plan passes the Plan Validator's contract check (its contract requires `recommendations` or `menu_items`). That makes it an LLM-reachable capability, not a guaranteed pipeline stage — describe it that way rather than as something every order necessarily passes through.

---

## Capabilities

### 1. Budget Validation
Checks the order total against configurable policy rules:

| Rule | Default | Effect |
|---|---|---|
| Per-meal cap | $30 | Orders above this are blocked |
| Daily budget | $50 | Cumulative daily spend limit |
| Auto-approval threshold | $25 | Orders above this require manager approval |

### 2. Three-Outcome Decision

```
Order Total
    |
    +--> Under $25: auto-approved (submitted)
    +--> $25-$30:   requires approval (pending_approval)
    +--> Over $30:  blocked (violation)
```

### 3. Violation Reporting
When rules are violated, returns structured violation objects:
```json
{
  "passed": false,
  "requires_approval": false,
  "violations": [
    {"rule": "per_meal_cap", "message": "Order exceeds $30 per-meal limit", "value": 35.00}
  ]
}
```

### 4. Configurable Rules
Policies are injected at agent construction time, making them easy to customize per department or organization without code changes.

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Strictly deterministic | Budget rules are business policy — an LLM should never decide whether to enforce them |
| Separate from Execution Agent | Policy validates, Execution acts. Clean separation means policy changes don't touch order logic |
| Approval routing, not blocking | Orders in the grey zone ($25-$30) aren't rejected — they're routed for human review |
| Currently advisory in demo | Full approval workflow (queue, manager UI, resume) was descoped in favor of the agent detecting and reporting the threshold |

---

## Pipeline Position

```
Recommendation --> (Planner proposed this step; Plan Validator accepted it)
                        |
                        v
                  [Policy Agent] --> Execution Agent
                        |
                   Validate order total
                   against policy rules
                        |
                   passed: true/false
                   requires_approval: true/false
                   violations: [...]
```

Not every order passes through this box — only plans the Planner explicitly proposed to include it.

**Reads from state:** recommendations (to calculate total), menu_items
**Writes to state:** policy_result, requires_approval
