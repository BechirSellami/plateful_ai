from typing import Any

import structlog
from mem0 import MemoryClient

from plateful.core.config import settings

logger = structlog.get_logger()


def get_mem0_client() -> MemoryClient:
    return MemoryClient(api_key=settings.mem0_api_key)


async def search_memories(
    client: MemoryClient,
    *,
    query: str,
    user_id: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    try:
        response = client.search(
            query=query,
            filters={"user_id": user_id},
            limit=limit,
        )
        results = response.get("results", []) if isinstance(response, dict) else response
        logger.info(
            "mem0_search_complete",
            user_id=user_id,
            query=query[:50],
            results_count=len(results),
        )
        return results  # type: ignore[no-any-return]
    except Exception:
        logger.exception("mem0_search_failed", user_id=user_id)
        return []


async def add_memories(
    client: MemoryClient,
    *,
    messages: list[dict[str, str]],
    user_id: str,
) -> dict[str, Any]:
    try:
        result = client.add(messages=messages, user_id=user_id)
        logger.info("mem0_add_complete", user_id=user_id)
        return result  # type: ignore[no-any-return]
    except Exception:
        logger.exception("mem0_add_failed", user_id=user_id)
        return {}


async def get_all_memories(
    client: MemoryClient,
    *,
    user_id: str,
) -> list[dict[str, Any]]:
    try:
        response = client.get_all(filters={"user_id": user_id})
        results = response.get("results", []) if isinstance(response, dict) else response
        return results  # type: ignore[no-any-return]
    except Exception:
        logger.exception("mem0_get_all_failed", user_id=user_id)
        return []
