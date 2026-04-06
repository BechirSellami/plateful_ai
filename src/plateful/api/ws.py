"""WebSocket handler for real-time chat with the catering agent.

Provides a persistent connection per user session. Each message goes
through the planner-driven orchestrator and streams back step-by-step
progress plus the final result.

Protocol (JSON over WS):
  Client -> Server:  {"message": "...", "user_id": "...", "session_id": "..."}
  Server -> Client:  {"type": "step",   "step": "plan", "agent": "planner"}
                     {"type": "step",   "step": "<reason>", "agent": "<agent>"}
                     {"type": "result", "intent": "...", ...}
                     {"type": "error",  "detail": "..."}
"""

from typing import Any

import structlog
from fastapi import WebSocket, WebSocketDisconnect

from plateful.agents.planner import PlannerAgent
from plateful.core.observability import TracingContext, trace_agent_step
from plateful.core.orchestrator import run_workflow
from plateful.core.workflow import WorkflowState

logger = structlog.get_logger()


async def websocket_chat(ws: WebSocket, registry: dict[str, Any], planner: PlannerAgent) -> None:
    """Handle a single WebSocket chat session."""
    await ws.accept()

    try:
        while True:
            data: dict[str, Any] = await ws.receive_json()

            message = data.get("message", "").strip()
            user_id = data.get("user_id", "emp_demo")
            session_id = data.get("session_id", "sess_demo")

            if not message:
                await ws.send_json({"type": "error", "detail": "Empty message"})
                continue

            # Build state
            state = WorkflowState(
                user_id=user_id,
                session_id=session_id,
                messages=[{"role": "user", "content": message}],
            )

            try:
                # Attach observability trace
                tracing = TracingContext.create(
                    trace_id=state.trace_id,
                    user_id=user_id,
                    session_id=session_id,
                )
                state._tracing = tracing  # type: ignore[attr-defined]

                # Phase 1: plan
                await ws.send_json({"type": "step", "step": "plan", "agent": "planner"})
                with trace_agent_step(tracing, agent_name="planner", step_name="plan"):
                    available = {k for k in registry}
                    plan_result = await planner.plan(state, available)

                # Phase 2: execute plan
                plan_steps = plan_result.get("plan", [])
                flow_steps = [
                    {"name": step.get("reason", step["agent"]), "agent": step["agent"]}
                    for step in plan_steps
                ]
                flow_def: dict[str, Any] = {"steps": flow_steps}

                # Audit callback that streams step progress to the client
                def make_audit_fn(websocket: WebSocket):  # type: ignore[no-untyped-def]
                    async def _audit(**kwargs: Any) -> None:
                        step = kwargs.get("step", "")
                        agent = kwargs.get("agent", "")
                        await websocket.send_json({"type": "step", "step": step, "agent": agent})

                    return _audit

                state = await run_workflow(flow_def, state, registry, audit_fn=make_audit_fn(ws))
                tracing.flush()

                # Build result payload
                result: dict[str, Any] = {
                    "type": "result",
                    "intent": state.intent,
                    "constraints": state.constraints,
                    "menu_items_count": len(state.menu_items),
                    "recommendations": [
                        {
                            "name": r.get("name"),
                            "price_usd": r.get("price_usd"),
                            "category": r.get("category"),
                            "cuisine": r.get("cuisine"),
                            "calories": r.get("calories"),
                            "description": r.get("description"),
                        }
                        for r in state.recommendations
                    ],
                    "recommendation_text": state.recommendation_text,
                    "order": state.order,
                    "user_profile": state.user_profile,
                }

                await ws.send_json(result)

            except Exception:
                logger.exception("ws_pipeline_error")
                await ws.send_json({"type": "error", "detail": "Pipeline error"})

    except WebSocketDisconnect:
        logger.info("ws_disconnected")
