"""EPISODIC memory service — full execution episodes stored in MySQL + FAISS."""
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

EPISODES_TABLE = "execution_episodes"
MEMORY_TABLE = "agent_memory_extended"
TIER = "EPISODIC"


class EpisodicMemoryService:
    def __init__(
        self,
        mysql: AsyncMySQLAdapter | None = None,
        faiss: FAISSAdapter | None = None,
        embedding: EmbeddingService | None = None,
    ) -> None:
        self._mysql = mysql or get_mysql_adapter()
        self._faiss = faiss or get_faiss_adapter()
        self._embedding = embedding or get_embedding_service()

    async def store_episode(self, agent_id: int, episode: dict[str, Any]) -> str:
        """Persist a full execution episode. Returns episode_id."""
        span_id = new_span_id()
        episode_id = str(uuid.uuid4())

        task_description = episode.get("task_description", "")
        output = episode.get("output", "")
        embed_text = f"Task: {task_description}\nOutput: {output}"

        vector = await self._embedding.embed(embed_text)
        # Store vector in per-agent FAISS using episode_id as the key
        await self._faiss.add(agent_id, vector, episode_id)

        # Insert into execution_episodes table
        row = {
            "episode_id": episode_id,
            "agent_id": agent_id,
            "session_id": episode.get("task_id", str(uuid.uuid4())),
            "task_description": task_description,
            "steps_taken": json.dumps(episode.get("steps", [])),
            "final_output": output,
            "final_score": episode.get("score", 0.0),
            "outcome": episode.get("outcome", "SUCCESS"),
            "importance_score": episode.get("importance", 0.5),
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        }
        await self._mysql.insert(EPISODES_TABLE, row)

        # Also write a cross-reference in agent_memory_extended for unified retrieval
        mem_row = {
            "agent_id": agent_id,
            "memory_tier": TIER,
            "content": embed_text,
            "content_vector_id": episode_id,
            "metadata": json.dumps({"episode_id": episode_id, **episode.get("metadata", {})}),
            "relevance_score": episode.get("score", 0.5),
            "access_count": 0,
            "last_accessed": None,
            "decay_factor": 1.0,
            "expires_at": None,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        }
        await self._mysql.insert(MEMORY_TABLE, mem_row)

        logger.info(
            "EPISODIC store_episode",
            layer="service",
            agent_id=agent_id,
            episode_id=episode_id,
            span_id=span_id,
        )
        return episode_id

    async def retrieve_similar(self, agent_id: int, query: str, k: int = 2) -> list[dict[str, Any]]:
        """Retrieve episodes semantically similar to the query."""
        span_id = new_span_id()

        if not query.strip():
            return []

        query_vec = await self._embedding.embed(query)
        faiss_hits = await self._faiss.search(agent_id, query_vec, k * 3)

        if not faiss_hits:
            return []

        episode_ids = [hit[0] for hit in faiss_hits]
        scores_by_id = {hit[0]: hit[1] for hit in faiss_hits}

        placeholders = ", ".join(["%s"] * len(episode_ids))

        # Try fetching from execution_episodes first
        rows = await self._mysql.execute(
            f"SELECT * FROM {EPISODES_TABLE} WHERE episode_id IN ({placeholders})",
            tuple(episode_ids),
            fetch=True,
        )

        results: list[dict[str, Any]] = []
        found_ids: set[str] = set()

        for row in (rows or []):
            row_dict = dict(row)
            eid = row_dict.get("episode_id", "")
            row_dict["similarity_score"] = scores_by_id.get(eid, 0.0)
            try:
                row_dict["steps"] = json.loads(row_dict.get("steps_taken") or "[]")
                row_dict["metadata"] = json.loads(row_dict.get("input_context") or "{}")
            except (json.JSONDecodeError, TypeError):
                row_dict["steps"] = []
                row_dict["metadata"] = {}
            results.append(row_dict)
            found_ids.add(eid)

        # Fall back to agent_memory_extended for IDs not found
        missing_ids = [eid for eid in episode_ids if eid not in found_ids]
        if missing_ids:
            placeholders2 = ", ".join(["%s"] * len(missing_ids))
            mem_rows = await self._mysql.execute(
                f"SELECT * FROM {MEMORY_TABLE} WHERE content_vector_id IN ({placeholders2}) AND memory_tier='{TIER}'",
                tuple(missing_ids),
                fetch=True,
            )
            for row in (mem_rows or []):
                row_dict = dict(row)
                eid = row_dict.get("content_vector_id", "")
                row_dict["similarity_score"] = scores_by_id.get(eid, 0.0)
                try:
                    row_dict["metadata"] = json.loads(row_dict.get("metadata") or "{}")
                except (json.JSONDecodeError, TypeError):
                    row_dict["metadata"] = {}
                results.append(row_dict)

        results.sort(key=lambda r: r["similarity_score"], reverse=True)

        logger.info(
            "EPISODIC retrieve_similar",
            layer="service",
            agent_id=agent_id,
            hits=len(results[:k]),
            span_id=span_id,
        )
        return results[:k]
