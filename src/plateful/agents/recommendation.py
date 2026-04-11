"""Recommendation Agent: ranks items and generates personalized suggestions.

Uses a two-stage approach:
1. Deterministic scoring (rank_items) for a baseline ranking
2. LLM reasoning (Claude) to generate natural-language recommendations

If no Claude API key is configured, falls back to deterministic-only mode.
"""

from typing import Any

import structlog

from plateful.core.config import settings
from plateful.core.workflow import WorkflowState
from plateful.tools.recommendation_tools import format_recommendations_prompt, rank_items

logger = structlog.get_logger()

RECOMMENDATION_SYSTEM_PROMPT = """You are the Recommendation Agent for a corporate catering service.
Your job is to suggest the best meal options for the employee.

Rules:
- The user's CURRENT REQUEST is the top priority. If they ask for specific foods \
(e.g. "pasta", "sandwich", "salad"), your recommendations MUST prioritise items \
that match what they asked for.
- Stored preferences and past orders are secondary context — use them to break ties \
or add colour, but NEVER override what the user explicitly asked for.
- Always recommend exactly 3 items (or fewer if less are available)
- Explain briefly why each item is a good match
- Be concise, warm, and helpful
- If the user has dietary restrictions or allergies, acknowledge them
- Mention the price for each recommendation
- Do NOT recommend items that conflict with stated allergies or restrictions
"""


class RecommendationAgent:
    """Rank items and generate personalized meal suggestions.

    Operates in two modes:
    - With Claude API key: LLM-powered natural language recommendations
    - Without API key: Deterministic scoring only (graceful degradation)
    """

    def __init__(self, anthropic_client: Any | None = None) -> None:
        self._client = anthropic_client

    async def run(self, state: WorkflowState) -> WorkflowState:
        items = state.menu_items
        profile = state.user_profile
        constraints = state.constraints

        if not items:
            state.recommendations = []
            state.last_result = "No items available to recommend."
            logger.info("recommendation_agent_skip", reason="no_items", trace_id=state.trace_id)
            return state

        # Extract the user's current message for context
        user_message = ""
        if state.messages:
            user_message = state.messages[-1].get("content", "")

        # Stage 1: Deterministic scoring (current request outweighs stored prefs)
        ranked = rank_items(items, profile, user_message=user_message)
        top_items = ranked[:5]  # send top 5 to LLM for final selection

        # Stage 2: LLM recommendation (if client available)
        recommendation_text = None
        if self._client and settings.anthropic_api_key:
            recommendation_text = await self._generate_llm_recommendation(
                top_items, profile, constraints, user_message=user_message, state=state
            )

        # If no LLM, use deterministic fallback
        if not recommendation_text:
            recommendation_text = self._format_deterministic_recommendation(top_items)

        state.recommendations = top_items[:3]
        state.recommendation_text = recommendation_text
        state.last_result = recommendation_text

        logger.info(
            "recommendation_agent_complete",
            trace_id=state.trace_id,
            items_ranked=len(ranked),
            top_3=[item["name"] for item in top_items[:3]],
            llm_used=recommendation_text is not None and self._client is not None,
        )

        return state

    async def _generate_llm_recommendation(
        self,
        items: list[dict[str, Any]],
        profile: dict[str, Any],
        constraints: dict[str, Any],
        *,
        user_message: str = "",
        state: WorkflowState | None = None,
    ) -> str | None:
        """Use Claude to generate a natural-language recommendation."""
        try:
            from plateful.core.observability import null_llm_trace, trace_llm_call

            prompt = format_recommendations_prompt(
                items, profile, constraints, user_message=user_message
            )

            # Get tracing context for LLM generation recording
            tracing = getattr(state, "_tracing", None) if state else None
            model = "claude-sonnet-4-20250514"

            if tracing is not None and tracing.is_active:
                gen_ctx = trace_llm_call(
                    tracing, name="recommendation.llm", model=model, input_data=prompt
                )
            else:
                gen_ctx = null_llm_trace()

            async with gen_ctx as gen:
                response = await self._client.messages.create(  # type: ignore[union-attr]
                    model=model,
                    system=RECOMMENDATION_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=512,
                )
                gen.update(
                    output=response.content[0].text if response.content else "",
                    usage_details={
                        "input": response.usage.input_tokens,
                        "output": response.usage.output_tokens,
                    },
                ).end()

            for block in response.content:
                if block.type == "text":
                    return block.text  # type: ignore[no-any-return]

        except Exception:
            logger.exception("llm_recommendation_failed")

        return None

    def _format_deterministic_recommendation(self, items: list[dict[str, Any]]) -> str:
        """Format a simple text recommendation without LLM."""
        if not items:
            return "No items match your criteria."

        lines = ["Here are my top picks for you:\n"]
        for i, item in enumerate(items[:3], 1):
            score = item.get("score", 0)
            lines.append(
                f"{i}. **{item['name']}** — ${item.get('price_usd', '?')}"
                f" ({item.get('category', '')}, {item.get('cuisine', '')})"
                f" [{item.get('calories', '?')} cal, match: {score}]"
            )
            if item.get("description"):
                lines.append(f"   {item['description']}")

        return "\n".join(lines)
