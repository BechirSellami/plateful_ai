# Execution Agent

**Type:** Action / Side-Effect | **LLM:** None | **Priority:** Core

---

## Role

The Execution Agent is the **order fulfillment endpoint** of the pipeline. It takes a confirmed item selection or a finalized meal plan, creates an order record, and sends a confirmation notification. It also respects policy decisions — if the Policy Agent flagged a violation, the Execution Agent blocks the order.

---

## Capabilities

### 1. Single-Item Order Submission
Resolves which item to order using a priority chain:

| Priority | Source | Example |
|---|---|---|
| 1st | `constraints.selected_item` | User said *"I'll take the Grilled Chicken Bowl"* |
| 2nd | Top recommendation | First item from the Recommendation Agent's ranked list |
| 3rd | First menu item | Fallback when no recommendation exists |

Supports fuzzy matching: *"the chicken bowl"* matches *"Grilled Chicken Bowl"* by keyword overlap.

### 2. Meal Plan Submission
When `intent == submit_mealplan`, converts the active 5-day plan into a **multi-item weekly order**:
- Extracts all plan entries (Monday–Friday) as order line items
- Calculates the weekly total
- Submits as a single order with all 5 items
- Returns a confirmation with order ID, item count, and total

### 3. Policy Enforcement
Checks the upstream Policy Agent's result before proceeding:
- **Passed** -> submit order normally
- **Requires approval** -> submit with `pending_approval` status
- **Blocked** -> reject the order with violation messages

### 4. Confirmation Notification
After order submission, sends a notification (simulated for demo) with:
- Order ID and status
- Item name(s) and total price
- Appropriate message for submitted vs. pending approval

---

## Design Decisions

| Decision | Rationale |
|---|---|
| No LLM involvement | Order placement is a deterministic action — no room for hallucination |
| Fuzzy item resolution | Users say *"the chicken"* not *"Grilled Chicken Bowl (ID: 42)"* — flexible matching improves UX |
| Separate single vs. meal plan paths | Meal plan orders are structurally different (5 items, one order) — clean separation avoids conditionals |
| Policy check is upstream, not inline | Separation of concerns: policy validates, execution acts. The Execution Agent trusts the policy result |

---

## Pipeline Position

```
Recommendation / MealPlan --> (Policy) --> [Execution Agent] --> Learning
                                                |
                                           Submit order
                                           Send notification
                                                |
                                                v
                                          state.order = {
                                            order_id: "ord_abc123",
                                            status: "submitted",
                                            items: [...],
                                            total_usd: 18.50
                                          }
```

**Reads from state:** intent, recommendations, constraints.selected_item, meal_plan, policy_result
**Writes to state:** order, recommendation_text (for meal plan confirmations)
