"""FastAPI application entry point."""

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from plateful.agents.intent import IntentAgent
from plateful.agents.menu import MenuAgent
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
    user_profile: dict[str, Any]


def _build_agent_registry() -> dict[str, Any]:
    """Build agent registry with available agents (no external deps needed)."""
    return {
        "orchestrator": IntentAgent(),
        "menu": MenuAgent(menu_data=SAMPLE_MENU),
        # Agents requiring external services are stubbed for now
    }


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Process a user message through the orchestrator pipeline.

    Runs intent classification and menu retrieval.
    Memory and recommendation agents are skipped when Mem0/Claude keys aren't configured.
    """
    state = WorkflowState(
        user_id=request.user_id,
        session_id=request.session_id,
        messages=[{"role": "user", "content": request.message}],
    )

    registry = _build_agent_registry()

    # Run only the steps we have agents for
    flow = {
        "steps": [
            {"name": "understand", "agent": "orchestrator"},
            {"name": "retrieve", "agent": "menu"},
        ]
    }

    state = await run_workflow(flow, state, registry)

    return ChatResponse(
        intent=state.intent,
        constraints=state.constraints,
        menu_items=state.menu_items,
        user_profile=state.user_profile,
    )


@app.get("/api/menu")
async def get_menu() -> list[dict[str, Any]]:
    """Return the full menu."""
    return SAMPLE_MENU
