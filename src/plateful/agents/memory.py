from typing import Any

import structlog
from mem0 import MemoryClient

from plateful.core.mem0_client import search_memories
from plateful.core.workflow import WorkflowState

logger = structlog.get_logger()


class MemoryAgent:
    """Read path: retrieves user preferences from Mem0 at query time.

    Enriches the workflow state with the user's profile
    by searching Mem0 for relevant memories based on the current context.
    """

    def __init__(self, client: MemoryClient) -> None:
        self._client = client

    async def run(self, state: WorkflowState) -> WorkflowState:
        query = self._build_context_query(state)
        logger.info(
            "memory_agent_query",
            query=query,
            trace_id=state.trace_id,
            user_id=state.user_id,
            intent=state.intent,
        )

        memories = await search_memories(
            self._client,
            query=query,
            user_id=state.user_id,
            limit=10,
        )

        state.user_profile = self._build_profile(memories)
        state.last_result = state.user_profile

        logger.info(
            "memory_agent_complete",
            trace_id=state.trace_id,
            user_id=state.user_id,
            memories_found=len(memories),
            profile_keys=list(state.user_profile.keys()),
        )

        return state

    def _build_context_query(self, state: WorkflowState) -> str:
        parts = []

        if state.intent:
            parts.append(f"User wants to {state.intent}")

        if state.constraints:
            constraint_parts = []
            if "budget" in state.constraints:
                constraint_parts.append(f"budget under ${state.constraints['budget']}")
            if "dietary" in state.constraints:
                constraint_parts.append(f"dietary: {state.constraints['dietary']}")
            if "meal_type" in state.constraints:
                constraint_parts.append(f"meal: {state.constraints['meal_type']}")
            if constraint_parts:
                parts.append(f"Constraints: {', '.join(constraint_parts)}")

        if not parts:
            parts.append("food preferences and dietary restrictions")

        return ". ".join(parts)

    def _build_profile(self, memories: list[dict[str, Any]]) -> dict[str, Any]:
        profile: dict[str, Any] = {
            "preferences": [],
            "allergies": [],
            "dietary_restrictions": [],
            "favorite_cuisines": [],
            "disliked_items": [],
            "budget_preference": None,
            "raw_memories": memories,
        }

        for memory in memories:
            text = memory.get("memory", "").lower()

            if any(word in text for word in ["allerg", "intoleran"]):
                profile["allergies"].append(memory.get("memory", ""))
            elif any(word in text for word in ["vegan", "vegetarian", "halal", "kosher", "gluten"]):
                profile["dietary_restrictions"].append(memory.get("memory", ""))
            elif any(word in text for word in ["avoids", "dislikes", "doesn't like", "hates"]):
                profile["disliked_items"].append(memory.get("memory", ""))
            elif any(word in text for word in ["prefers", "likes", "loves", "enjoys", "favorite"]):
                profile["preferences"].append(memory.get("memory", ""))
            elif any(word in text for word in ["budget", "spend", "under $", "cheap"]):
                profile["budget_preference"] = memory.get("memory", "")
            else:
                profile["preferences"].append(memory.get("memory", ""))

        return profile
