# Plateful AI

Plateful AI is an agentic catering assistant for employee meal ordering,
recommendations, and weekly meal planning. It demonstrates a production-minded
multi-agent architecture in a concrete workplace workflow: understand the user,
retrieve relevant context, filter safely, recommend meals, place orders, and
learn from the outcome.

Built with Python 3.12+, FastAPI, SQLAlchemy (async), Postgres, Mem0 Cloud, and the Claude API.

## What this demonstrates

**LLM planning with deterministic control.** Claude classifies intent, extracts
structured constraints, and detects compound requests such as "I love spicy food;
order the tofu today." The actual agent sequence is composed by a deterministic
flow router, so the LLM informs the workflow without owning execution order.

**Purpose-built agents with clear responsibilities.**

| Agent | Responsibility |
|---|---|
| Planner | Converts a user turn into intent, constraints, compound flags, and an execution plan |
| Memory | Retrieves user preferences, allergies, dietary restrictions, and order history from Mem0 |
| Menu | Fetches menu items and applies deterministic filters for budget, cuisine, availability, and allergens |
| Recommendation | Ranks items deterministically, then uses Claude for concise personalized recommendations |
| Meal Plan | Generates or edits a Monday-Friday meal plan and keeps it active across turns |
| Execution | Resolves selected items, submits orders, and sends confirmations |
| Learning | Writes preferences, accepted suggestions, and submitted orders back to long-term memory |

**Compound request handling.** The planner can route one message through multiple
agents. For example, a recommendation request that also declares an allergy can
retrieve memory, fetch a safe menu, recommend options, and persist the new
preference in the same turn.

**Safety where it matters.** Allergen filtering is deterministic and runs outside
the LLM. Unsafe requested items are removed before recommendation, and the user
receives an explicit warning plus safe alternatives.

**Stateful real-time product flow.** A WebSocket chat session carries forward
meal plans, menu items, and recommendations across turns, enabling natural flows
such as "swap Tuesday for pasta" or "yes, order it."

**Observability and auditability.** Each planner and agent step records structured
inputs and outputs for trace inspection, including LLM token usage when available.
Agent contracts validate planned workflows in warn mode, and audit snapshots can
be persisted to Postgres after each step.

**Graceful degradation.** If Claude or Mem0 is unavailable, the app can still run
with deterministic keyword planning and scoring, keeping the demo usable without
external AI services.

## Architecture at a glance

```text
User message
  -> PlannerAgent
       -> intent + constraints + compound flags
       -> deterministic flow_router.compose_plan()
  -> Ordered agent workflow
       -> memory -> menu -> recommendation / mealplan / execution -> learning
  -> WebSocket/API response + traces + audit snapshots
```

## Setup

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Start Postgres
docker compose up -d

# Run database migrations
alembic upgrade head
```

### Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | Yes | Async Postgres connection string |
| `ANTHROPIC_API_KEY` | No | Enables LLM-powered recommendations via Claude |
| `MEM0_API_KEY` | No | Enables Mem0 Cloud memory |

Without `ANTHROPIC_API_KEY`, the app runs in deterministic-only mode.

## Running the app

### API server

```bash
uvicorn plateful.api.app:app --reload
```

Then test with:

```bash
curl http://localhost:8000/health

curl http://localhost:8000/api/menu

curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "I want something vegetarian under $15"}'
```

API docs are available at http://localhost:8000/docs.

### Frontend

In a separate terminal:

```bash
cd frontend
npm run dev
```

The frontend (React + Vite) will be available at http://localhost:5173. The backend must also be running at http://localhost:8000.

### Interactive CLI

```bash
python -m plateful.cli
```

## Running tests

```bash
# Unit tests
pytest tests/unit -m unit

# Integration tests (requires Postgres)
pytest tests/integration -m integration

# Lint and format
ruff check src/ tests/
ruff format src/ tests/

# Type check
mypy src/
```
