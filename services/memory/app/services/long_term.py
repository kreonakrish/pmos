"""LONG_TERM memory service — MySQL + per-agent FAISS shards."""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.adapters.faiss_adapter import FAISSAdapter, get_faiss_adapter
from app.adapters.mysql_adapter import AsyncMySQLAdapter, get_mysql_adapter
from app.utils.embedding import EmbeddingService, get_embedding_service
from app.utils.logger import get_logger, new_span_id

logger = get_logger()

TABLE = "agent_memory_extended"


class LongTermMemoryService:
    def __init__(
        self,
        mysql: AsyncMySQLAdapter | None = None,
        faiss: FAISSAdapter | None = None,
        embedding: EmbeddingService | None = None,
    ) -> None:
        self._mysql = mysql or get_mysql_adapter()
        self._faiss = faiss or get_faiss_adapter()
        self._embedding = embedding or get_embedding_service()

    async def store(self, agent_id: int, content: str, metadata: dict[str, Any]) -> str:
        """Embed content, add to FAISS shard, insert MySQL row. Returns memory_id."""
        span_id = new_span_id()
        memory_id = str(uuid.uuid4())

        vector = await self._embedding.embed(content)
        await self._faiss.add(agent_id, vector, memory_id)

        row = {
            "agent_id": agent_id,
            "memory_tier": "LONG_TERM",
            "content": content,
            "content_vector_id": memory_id,
            "metadata": json.dumps(metadata),
            "relevance_score": metadata.get("importance", 0.5),
            "access_count": 0,
            "last_accessed": None,
            "decay_factor": 1.0,
            "expires_at": None,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        }
        await self._mysql.insert(TABLE, row)

        logger.info(
            "LONG_TERM store",
            layer="service",
            agent_id=agent_id,
            memory_id=memory_id,
            span_id=span_id,
        )
        return memory_id

    async def semantic_search(self, agent_id: int, query: str, k: int = 5) -> list[dict[str, Any]]:
        """Embed query, search FAISS shard, retrieve MySQL rows by IDs."""
        span_id = new_span_id()

        if not query.strip():
            return []

        query_vec = await self._embedding.embed(query)
        faiss_hits = await self._faiss.search(agent_id, query_vec, k)

        if not faiss_hits:
            return []

        memory_ids = [hit[0] for hit in faiss_hits]
        scores_by_id = {hit[0]: hit[1] for hit in faiss_hits}

        placeholders = ", ".join(["%s"] * len(memory_ids))
        rows = await self._mysql.execute(
            f"SELECT * FROM {TABLE} WHERE content_vector_id IN ({placeholders}) AND memory_tier='LONG_TERM'",
            tuple(memory_ids),
            fetch=True,
        )

        if not rows:
            return []

        # Attach FAISS scores and update access counts
        results: list[dict[str, Any]] = []
        for row in rows:
            row_dict = dict(row)
            row_dict["similarity_score"] = scores_by_id.get(row_dict.get("content_vector_id", ""), 0.0)
            try:
                row_dict["metadata"] = json.loads(row_dict.get("metadata") or "{}")
            except (json.JSONDecodeError, TypeError):
                row_dict["metadata"] = {}
            results.append(row_dict)

            # Increment access_count
            await self._mysql.execute(
                f"UPDATE {TABLE} SET access_count = access_count + 1, last_accessed = NOW() WHERE content_vector_id = %s",
                (row_dict.get("content_vector_id"),),
            )

        results.sort(key=lambda r: r["similarity_score"], reverse=True)

        logger.info(
            "LONG_TERM semantic_search",
            layer="service",
            agent_id=agent_id,
            hits=len(results),
            span_id=span_id,
        )
        return results
