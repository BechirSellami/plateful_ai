"""FastAPI application entry point."""

from typing import Any

import anthropic
from fastapi import FastAPI
from pydantic import BaseModel

from plateful.agents.intent import IntentAgent
from plateful.agents.menu import MenuAgent
from plateful.agents.recommendation import RecommendationAgent
from plateful.core.config import settings
from plateful.core.orchestrator import run_workflow
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

    return {
        "orchestrator": IntentAgent(),
        "menu": MenuAgent(menu_data=SAMPLE_MENU),
        "recommendation": RecommendationAgent(anthropic_client=claude_client),
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a user message through the orchestrator pipeline.

    Runs intent classification, menu retrieval, and recommendation.
    """
    state = WorkflowState(
        user_id=request.user_id,
        session_id=request.session_id,
        messages=[{"role": "user", "content": request.message}],
    )

    registry = _build_agent_registry()

    flow = {
        "steps": [
            {"name": "understand", "agent": "orchestrator"},
            {"name": "retrieve", "agent": "menu"},
            {"name": "recommend", "agent": "recommendation"},
        ]
    }

    state = await run_workflow(flow, state, registry)

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
