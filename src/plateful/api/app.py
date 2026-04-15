"""FastAPI application entry point."""

from datetime import datetime
from pathlib import Path
from typing import Any

import anthropic
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mem0 import MemoryClient
from pydantic import BaseModel

from plateful.agents.execution import ExecutionAgent
from plateful.agents.learning import LearningAgent
from plateful.agents.memory import MemoryAgent
from plateful.agents.menu import MenuAgent
from plateful.agents.planner import PlannerAgent
from plateful.agents.recommendation import RecommendationAgent
from plateful.core.audit import make_audit_fn
from plateful.core.config import settings
from plateful.core.mem0_client import get_all_memories, get_mem0_client, search_memories
from plateful.core.orchestrator import run_planned_workflow
from plateful.core.seed_data import SAMPLE_MENU
from plateful.core.workflow import WorkflowState
from plateful.db.session import async_session_factory

app = FastAPI(title="Plateful AI", description="Catering Agent API", version="0.1.0")

# Static files (Chat UI built by Vite into ../static/)
_STATIC_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static"
_ASSETS_DIR = _STATIC_DIR / "assets"
if _ASSETS_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="assets")


class ChatRequest(BaseModel):
    message: str
    user_id: str = "emp_demo"
    session_id: str = "sess_demo"


class ChatResponse(BaseModel):
    intent: str | None
    constraints: dict[str, Any]
    menu_items: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    recommendation_text: str | None
    user_profile: dict[str, Any]


def _get_claude_client() -> anthropic.AsyncAnthropic | None:
    if settings.anthropic_api_key:
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return None


def _build_planner(claude_client: anthropic.AsyncAnthropic | None) -> PlannerAgent:
    if claude_client:
        return PlannerAgent(mode="llm", anthropic_client=claude_client)
    return PlannerAgent(mode="keyword")


def _build_agent_registry() -> dict[str, Any]:
    """Build agent registry with available agents."""
    claude_client = _get_claude_client()

    # Memory + Learning agents (require Mem0 API key)
    registry: dict[str, Any] = {
        "menu": MenuAgent(menu_data=SAMPLE_MENU),
        "recommendation": RecommendationAgent(anthropic_client=claude_client),
        "execution": ExecutionAgent(),
    }
    if settings.mem0_api_key:
        mem0_client = get_mem0_client()
        registry["memory"] = MemoryAgent(client=mem0_client)
        registry["learning"] = LearningAgent(client=mem0_client)

    return registry


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a user message through the planner-driven orchestrator.

    Phase 1: Planner builds an execution plan (handles compound intents).
    Phase 2: Execute the plan sequentially.

    Audit: Each agent step is persisted to the audit_trail table.
    """
    state = WorkflowState(
        user_id=request.user_id,
        session_id=request.session_id,
        messages=[{"role": "user", "content": request.message}],
    )

    registry = _build_agent_registry()
    planner = _build_planner(_get_claude_client())

    async with async_session_factory() as session:
        audit_fn = make_audit_fn(session)
        state = await run_planned_workflow(state, registry, planner, audit_fn=audit_fn)
        await session.commit()

    return ChatResponse(
        intent=state.intent,
        constraints=state.constraints,
        menu_items=state.menu_items,
        recommendations=state.recommendations,
        recommendation_text=state.recommendation_text,
        user_profile=state.user_profile,
    )


@app.get("/api/menu")
async def get_menu() -> list[dict[str, Any]]:
    """Return the full menu."""
    return SAMPLE_MENU


# --- Memory endpoints ------------------------------------------------------


def _require_mem0_client() -> MemoryClient:
    """Return a Mem0 client or raise 503 if not configured."""
    if not settings.mem0_api_key:
        raise HTTPException(status_code=503, detail="Mem0 is not configured (no MEM0_API_KEY)")
    return get_mem0_client()


@app.get("/api/memories/{user_id}")
async def list_memories(user_id: str) -> list[dict[str, Any]]:
    """List all stored memories for a user."""
    client = _require_mem0_client()
    return await get_all_memories(client, user_id=user_id)


@app.get("/api/memories/{user_id}/search")
async def search_user_memories(user_id: str, q: str, limit: int = 10) -> list[dict[str, Any]]:
    """Search memories for a user by query string."""
    client = _require_mem0_client()
    return await search_memories(client, query=q, user_id=user_id, limit=limit)


@app.delete("/api/memories/{user_id}")
async def delete_all_memories(user_id: str) -> dict[str, str]:
    """Delete all memories for a user."""
    client = _require_mem0_client()
    client.delete_all(filters={"user_id": user_id})
    return {"status": "deleted", "user_id": user_id}


@app.delete("/api/memories/{user_id}/{memory_id}")
async def delete_memory(user_id: str, memory_id: str) -> dict[str, str]:
    """Delete a specific memory by ID."""
    client = _require_mem0_client()
    client.delete(memory_id=memory_id)
    return {"status": "deleted", "memory_id": memory_id}


# --- Feedback / Scoring -------------------------------------------------------


class FeedbackRequest(BaseModel):
    trace_id: str
    score: float
    comment: str = ""


@app.post("/api/feedback")
async def submit_feedback(request: FeedbackRequest) -> dict[str, str]:
    """Submit user feedback for a trace (sent to Langfuse if configured)."""
    from plateful.core.observability import get_langfuse

    client = get_langfuse()
    if client is None:
        raise HTTPException(status_code=503, detail="Langfuse is not configured")

    client.create_score(
        trace_id=request.trace_id,
        name="user_feedback",
        value=request.score,
        comment=request.comment,
    )
    return {"status": "ok", "trace_id": request.trace_id}


# --- Audit viewer endpoints ---------------------------------------------------


@app.get("/api/audit/trace/{trace_id}")
async def get_trace_audit_log(trace_id: str) -> list[dict[str, Any]]:
    """Return all audit records for a specific trace (one user message)."""
    from plateful.db.audit_store import get_trace_audit

    async with async_session_factory() as session:
        rows = await get_trace_audit(session, trace_id=trace_id)
        return [
            {
                "id": str(row.id),
                "trace_id": str(row.trace_id),
                "timestamp": row.timestamp.isoformat(),
                "user_id": row.user_id,
                "agent": row.agent,
                "decision_type": row.decision_type.value,
                "input_snapshot": row.input_snapshot,
                "output_snapshot": row.output_snapshot,
                "reasoning": row.reasoning,
                "outcome": row.outcome.value,
            }
            for row in rows
        ]


@app.get("/api/audit/user/{user_id}")
async def get_user_audit_log(
    user_id: str,
    since: datetime | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return audit records for a user, most recent first."""
    from plateful.db.audit_store import get_user_audit

    async with async_session_factory() as session:
        rows = await get_user_audit(session, user_id=user_id, since=since, limit=limit)
        return [
            {
                "id": str(row.id),
                "trace_id": str(row.trace_id),
                "timestamp": row.timestamp.isoformat(),
                "user_id": row.user_id,
                "agent": row.agent,
                "decision_type": row.decision_type.value,
                "input_snapshot": row.input_snapshot,
                "output_snapshot": row.output_snapshot,
                "reasoning": row.reasoning,
                "outcome": row.outcome.value,
            }
            for row in rows
        ]


# --- WebSocket + UI ----------------------------------------------------------

from plateful.api.ws import websocket_chat  # noqa: E402


@app.websocket("/ws/chat")
async def ws_chat_endpoint(ws: WebSocket) -> None:
    registry = _build_agent_registry()
    planner = _build_planner(_get_claude_client())
    await websocket_chat(ws, registry, planner)


@app.get("/")
async def index() -> FileResponse:
    """Serve the Chat UI."""
    return FileResponse(str(_STATIC_DIR / "index.html"))
