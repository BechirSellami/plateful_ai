# Plateful AI - Catering Agent

## Project overview
Agentic catering assistant for employee meal ordering and planning.
Stack: Python 3.12+, FastAPI, SQLAlchemy (async), Postgres, Mem0 Cloud, Claude API.

## Architecture
- `src/plateful/` - main package
  - `agents/` - agent implementations (orchestrator, memory, menu, recommendation, policy, execution, learning)
  - `api/` - FastAPI routes and WebSocket handlers
  - `db/` - SQLAlchemy models and database session
  - `tools/` - tool functions called by agents
  - `core/` - config, logging, shared utilities
- `tests/unit/` - unit tests (no external deps)
- `tests/integration/` - integration tests (requires Postgres)
- `tests/evals/` - evaluation tests (may use LLM)
- `alembic/` - database migrations

## Commands
- `pip install -e ".[dev]"` - install with dev dependencies
- `pytest tests/unit -m unit` - run unit tests
- `pytest tests/integration -m integration` - run integration tests
- `ruff check src/ tests/` - lint
- `ruff format src/ tests/` - format
- `mypy src/` - type check
- `docker compose up -d` - start Postgres
- `alembic upgrade head` - run migrations

## Conventions
- All tests use pytest markers: `@pytest.mark.unit`, `@pytest.mark.integration`, `@pytest.mark.eval`
- Async-first: use `async def` for all agent and DB operations
- Type hints everywhere, enforced by mypy strict mode
- Structured logging via structlog
- Feature branches per build phase, PRs for review
