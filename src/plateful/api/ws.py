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
from plateful.core.audit import make_audit_fn
from plateful.core.observability import TracingContext, trace_agent_step
from plateful.core.orchestrator import run_workflow
from plateful.core.workflow import WorkflowState
from plateful.db.session import async_session_factory

logger = structlog.get_logger()


async def websocket_chat(ws: WebSocket, registry: dict[str, Any], planner: PlannerAgent) -> None:
    """Handle a single WebSocket chat session."""
    await ws.accept()

    # Session-level state that persists across turns
    session_meal_plan: dict[str, dict[str, Any]] = {}

    try:
        while True:
            data: dict[str, Any] = await ws.receive_json()

            message = data.get("message", "").strip()
            user_id = data.get("user_id", "emp_demo")
            session_id = data.get("session_id", "sess_demo")

            if not message:
                await ws.send_json({"type": "error", "detail": "Empty message"})
                continue

            # Build state, carrying forward the meal plan from prior turns
            state = WorkflowState(
                user_id=user_id,
                session_id=session_id,
                messages=[{"role": "user", "content": message}],
                meal_plan=dict(session_meal_plan),
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

                # Short-circuit for out-of-scope requests
                if plan_result.get("intent") == "out_of_scope":
                    state.recommendation_text = (
                        "I'm sorry, that's outside what I can help with. "
                        "I'm your catering assistant \u2014 I can help you with:\n"
                        "\u2022 Browsing today's menu and getting meal recommendations\n"
                        "\u2022 Placing and tracking lunch orders\n"
                        "\u2022 Saving your dietary preferences and allergies\n"
                        "\u2022 Planning meals for the week\n\n"
                        "What would you like to eat today?"
                    )
                    tracing.flush()
                else:
                    # Phase 2: execute plan
                    plan_steps = plan_result.get("plan", [])
                    flow_steps = [
                        {"name": step.get("reason", step["agent"]), "agent": step["agent"]}
                        for step in plan_steps
                    ]
                    flow_def: dict[str, Any] = {"steps": flow_steps}

                    # Compose two audit callbacks: stream progress + persist to DB
                    async with async_session_factory() as db_session:
                        _db_audit = make_audit_fn(db_session)

                        def _make_combined(websocket: WebSocket, db_fn: Any) -> Any:
                            async def _combined(**kwargs: Any) -> None:
                                step = kwargs.get("step", "")
                                agent = kwargs.get("agent", "")
                                await websocket.send_json(
                                    {"type": "step", "step": step, "agent": agent}
                                )
                                await db_fn(**kwargs)

                            return _combined

                        state = await run_workflow(
                            flow_def,
                            state,
                            registry,
                            audit_fn=_make_combined(ws, _db_audit),
                        )
                        await db_session.commit()
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
                    "allergen_conflicts": state.allergen_conflicts or [],
                    "meal_plan": state.meal_plan or None,
                }

                # Persist meal plan across turns
                if state.meal_plan:
                    session_meal_plan = dict(state.meal_plan)

                await ws.send_json(result)

            except Exception:
                logger.exception("ws_pipeline_error")
                await ws.send_json({"type": "error", "detail": "Pipeline error"})

    except WebSocketDisconnect:
        logger.info("ws_disconnected")
