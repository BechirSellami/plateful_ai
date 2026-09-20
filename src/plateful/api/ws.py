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
from plateful.core.conversation import (
    ERROR_ASSISTANT_TURN,
    MAX_HISTORY_MESSAGES,
    render_assistant_turn,
)
from plateful.core.observability import TracingContext, trace_agent_step
from plateful.core.orchestrator import resolve_validated_plan, run_workflow
from plateful.core.workflow import WorkflowState
from plateful.db.session import async_session_factory

logger = structlog.get_logger()


async def websocket_chat(ws: WebSocket, registry: dict[str, Any], planner: PlannerAgent) -> None:
    """Handle a single WebSocket chat session."""
    await ws.accept()

    # Session-level state that persists across turns.
    # ``session_messages`` is the linguistic layer (what was said, so the
    # planner can resolve "the second one"); the other three are the
    # authoritative structured layer (what the system actually has).
    session_messages: list[dict[str, str]] = []
    session_meal_plan: dict[str, dict[str, Any]] = {}
    session_menu_items: list[dict[str, Any]] = []
    session_recommendations: list[dict[str, Any]] = []

    def _record_turn(user_text: str, assistant_text: str) -> None:
        nonlocal session_messages
        session_messages = [
            *session_messages,
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_text},
        ][-MAX_HISTORY_MESSAGES:]

    try:
        while True:
            data: dict[str, Any] = await ws.receive_json()

            message = data.get("message", "").strip()
            user_id = data.get("user_id", "emp_demo")
            session_id = data.get("session_id", "sess_demo")

            if not message:
                await ws.send_json({"type": "error", "detail": "Empty message"})
                continue

            # Build state, carrying forward context from prior turns so
            # order_meal flows can resolve items seen during recommendation.
            # The current user message is always last in ``messages``.
            state = WorkflowState(
                user_id=user_id,
                session_id=session_id,
                messages=[*session_messages, {"role": "user", "content": message}],
                meal_plan=dict(session_meal_plan),
                menu_items=list(session_menu_items),
                recommendations=list(session_recommendations),
            )

            # Attach observability trace. The user message is the trace
            # input; the rendered assistant turn becomes its output below.
            tracing = TracingContext.create(
                trace_id=state.trace_id,
                user_id=user_id,
                session_id=session_id,
                input_data=message,
            )
            state._tracing = tracing  # type: ignore[attr-defined]

            try:
                # Phase 1: plan
                await ws.send_json({"type": "step", "step": "plan", "agent": "planner"})
                with trace_agent_step(tracing, agent_name="planner", step_name="plan") as plan_span:
                    available = {k for k in registry}
                    plan_result = await planner.plan(state, available)
                    plan_span.update(
                        input={"user_message": message},
                        output={
                            "intent": plan_result.get("intent"),
                            "constraints": plan_result.get("constraints", {}),
                            "compound_flags": plan_result.get("compound_flags", {}),
                            "plan": [s.get("agent") for s in plan_result.get("plan", [])],
                        },
                    )

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
                else:
                    # Phase 1.5: Plan Validator gate — same contract check
                    # and deterministic fallback as the HTTP/CLI path.
                    with trace_agent_step(
                        tracing, agent_name="plan_validator", step_name="validate_plan"
                    ) as validate_span:
                        flow_steps, validation, used_fallback = resolve_validated_plan(
                            plan_result, state, available
                        )
                        validate_span.update(
                            input={
                                "proposed_plan": [
                                    s.get("agent") for s in plan_result.get("plan", [])
                                ]
                            },
                            output={
                                **validation.summary(),
                                "used_fallback": used_fallback,
                                "executed_plan": [s["agent"] for s in flow_steps],
                            },
                        )

                    # Phase 2: execute plan
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

                # Build result payload.
                # When an order was placed, recommendations are stale
                # carry-forward data — omit them so the frontend shows
                # the order confirmation instead of misleading rec cards.
                has_order = bool(state.order)
                result: dict[str, Any] = {
                    "type": "result",
                    "intent": state.intent,
                    "constraints": state.constraints,
                    "menu_items_count": len(state.menu_items),
                    "recommendations": []
                    if has_order
                    else [
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

                # Persist context across turns
                if state.meal_plan:
                    session_meal_plan = dict(state.meal_plan)
                if state.menu_items:
                    session_menu_items = list(state.menu_items)
                if state.recommendations:
                    session_recommendations = list(state.recommendations)
                assistant_turn = render_assistant_turn(state)
                _record_turn(message, assistant_turn)
                tracing.flush(output=assistant_turn)

                await ws.send_json(result)

            except Exception:
                logger.exception("ws_pipeline_error")
                # Still record the exchange so the transcript keeps
                # alternating user/assistant turns.
                _record_turn(message, ERROR_ASSISTANT_TURN)
                tracing.flush(output=ERROR_ASSISTANT_TURN)
                await ws.send_json({"type": "error", "detail": "Pipeline error"})

    except WebSocketDisconnect:
        logger.info("ws_disconnected")
