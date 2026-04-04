"""Learning Agent: consolidates session events into long-term memory.

Write path counterpart to the Memory Agent (read path).
After an order is placed, this agent summarises what happened in the session
and feeds the summary to Mem0 so future sessions benefit from the learned
preferences.
"""

from typing import Any

import structlog
from mem0 import MemoryClient

from plateful.core.mem0_client import add_memories
from plateful.core.preference_signals import has_preference_signal
from plateful.core.workflow import WorkflowState
from plateful.tools.learning_tools import build_mem0_messages, summarize_session_events

logger = structlog.get_logger()


class LearningAgent:
    """Write path: distils session events into Mem0 memories."""

    def __init__(self, client: MemoryClient) -> None:
        self._client = client

    async def run(self, state: WorkflowState) -> WorkflowState:
        events = self._collect_events(state)

        if not events:
            logger.info(
                "learning_agent_skip",
                trace_id=state.trace_id,
                reason="no_events",
            )
            state.last_result = {"status": "skipped", "reason": "no events to learn from"}
            return state

        summary = summarize_session_events(events)

        if not summary:
            state.last_result = {"status": "skipped", "reason": "empty summary"}
            return state

        messages = build_mem0_messages(summary)
        mem0_result = await add_memories(
            self._client,
            messages=messages,
            user_id=state.user_id,
        )

        state.last_result = {
            "status": "learned",
            "events_processed": len(events),
            "summary": summary,
            "mem0_result": mem0_result,
        }

        logger.info(
            "learning_agent_complete",
            trace_id=state.trace_id,
            user_id=state.user_id,
            events_processed=len(events),
            summary_length=len(summary),
        )

        return state

    def _collect_events(self, state: WorkflowState) -> list[dict[str, Any]]:
        """Gather learning-worthy events from the workflow state.

        In production this would query the event store for the session.
        For now we synthesise events from the state itself.
        """
        events: list[dict[str, Any]] = []

        user_message = ""
        if state.messages:
            user_message = state.messages[-1].get("content", "")

        # Preference / constraint declarations from the conversation.
        # Detect preference signals from the user message regardless of
        # the classified intent — compound messages like "I love spicy
        # food, what do you recommend?" have intent=get_recommendation
        # but still contain a preference worth saving.
        has_preference = state.intent == "declare_preference" or has_preference_signal(user_message)

        if has_preference and user_message:
            events.append(
                {
                    "event_type": "preference_declared",
                    "payload": {"message": user_message},
                }
            )

            # Also capture any extracted constraints (dietary, cuisine, etc.)
            for key in ("dietary", "cuisine", "budget"):
                if key in state.constraints:
                    events.append(
                        {
                            "event_type": "allergy_declared"
                            if key == "dietary"
                            else "preference_declared",
                            "payload": {key: state.constraints[key]},
                        }
                    )

        # Order placed
        if state.order and state.order.get("status") == "submitted":
            for item in state.order.get("items", []):
                events.append(
                    {
                        "event_type": "order_placed",
                        "payload": {
                            "item_name": item.get("name", "Unknown"),
                            "price_usd": item.get("price_usd", 0),
                        },
                    }
                )

        # Recommendations that were surfaced (accepted implicitly if ordered)
        if state.recommendations and state.order:
            ordered_names = {item.get("name", "").lower() for item in state.order.get("items", [])}
            for rec in state.recommendations:
                name = rec.get("name", "")
                if name.lower() in ordered_names:
                    events.append(
                        {
                            "event_type": "suggestion_accepted",
                            "payload": {"item_name": name},
                        }
                    )

        return events
