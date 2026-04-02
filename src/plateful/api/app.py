"""FastAPI application entry point."""

from typing import Any

import anthropic
from fastapi import FastAPI, HTTPException
from mem0 import MemoryClient
from pydantic import BaseModel

from plateful.agents.intent import IntentAgent
from plateful.agents.learning import LearningAgent
from plateful.agents.memory import MemoryAgent
from plateful.agents.menu import MenuAgent
from plateful.agents.recommendation import RecommendationAgent
from plateful.core.config import settings
from plateful.core.mem0_client import get_all_memories, get_mem0_client, search_memories
from plateful.core.orchestrator import run_adaptive_workflow
from plateful.core.seed_data import SAMPLE_MENU
from plateful.core.workflow import WorkflowState

app = FastAPI(title="Plateful AI", description="Catering Agent API", version="0.1.0")


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


def _build_agent_registry() -> dict[str, Any]:
    """Build agent registry with available agents."""
    # Create Claude client if API key is configured
    claude_client = None
    if settings.anthropic_api_key:
        claude_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    intent_agent = (
        IntentAgent(mode="llm", anthropic_client=claude_client) if claude_client else IntentAgent()
    )

    # Memory + Learning agents (require Mem0 API key)
    registry: dict[str, Any] = {
        "orchestrator": intent_agent,
        "menu": MenuAgent(menu_data=SAMPLE_MENU),
        "recommendation": RecommendationAgent(anthropic_client=claude_client),
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
    """Process a user message through the adaptive orchestrator pipeline.

    Phase 1: classify intent.
    Phase 2: route to the appropriate flow based on intent.
    """
    state = WorkflowState(
        user_id=request.user_id,
        session_id=request.session_id,
        messages=[{"role": "user", "content": request.message}],
    )

    registry = _build_agent_registry()
    state = await run_adaptive_workflow(state, registry)

    return ChatResponse(
        intent=state.intent,
        constraints=state.constraints,
        menu_items=state.menu_items,
        recommendations=state.recommendations,
        recommendation_text=state.last_result if isinstance(state.last_result, str) else None,
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
