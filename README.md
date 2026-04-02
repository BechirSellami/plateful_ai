# Plateful AI

Agentic catering assistant for employee meal ordering and planning.

Built with Python 3.12+, FastAPI, SQLAlchemy (async), Postgres, Mem0 Cloud, and the Claude API.

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
