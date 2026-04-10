import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from tenacity import retry, RetryError, stop_after_attempt, wait_exponential

from app.adapters.base import SearchResult, VectorStoreAdapter
from app.adapters.mysql_fulltext import MySQLFullTextAdapter
from app.services.reranker import Reranker
from app.utils.embedding import embed_query
from app.utils.logger import get_logger

logger = get_logger(layer="retrieval")

# Deduplication threshold — discard results with near-identical content
_DEDUP_SIMILARITY_CHARS = 50  # compare first N chars


class RetrievalService:
    """
    Multi-source parallel retrieval.

    Sources:
        - Primary vector store (Qdrant / FAISS / Pinecone / Weaviate depending on config)
        - MySQL full-text search
        - Agent memory service (HTTP call)
    """

    def __init__(
        self,
        vector_store: VectorStoreAdapter,
        mysql_adapter: MySQLFullTextAdapter,
        reranker: Reranker,
        settings,
    ) -> None:
        self._vector_store = vector_store
        self._mysql = mysql_adapter
        self._reranker = reranker
        self._settings = settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def retrieve(
        self,
        query: str,
        agent_id: int,
        top_k: int,
        sources: Optional[List[str]],
        context: Optional[Dict[str, Any]],
        trace_id: str,
    ) -> dict:
        start_ms = int(time.monotonic() * 1000)
        log = logger.with_trace(trace_id)

        # Embed query once; shared by all vector-based sources
        query_vec = await embed_query(self._settings.embedding_model, query)

        active_sources = sources or ["qdrant", "mysql", "memory"]
        backend = self._settings.vector_store_backend  # e.g. "qdrant"

        tasks: List[asyncio.Task] = []
        source_labels: List[str] = []

        # Vector store (primary backend)
        # Map any vector store source name to the actual backend
        vector_source_names = {"qdrant", "faiss", "pinecone", "weaviate"}
        requested_vector = [s for s in (sources or []) if s in vector_source_names]
        if not sources or backend in (sources or []) or requested_vector:
            tasks.append(asyncio.create_task(
                self._safe_search_vector(query_vec, top_k, trace_id)
            ))
            # Use the requested source name if specified, otherwise use the backend name
            if requested_vector:
                source_labels.append(requested_vector[0])
            else:
                source_labels.append(backend)

        # MySQL full-text
        if not sources or "mysql" in (sources or []):
            tasks.append(asyncio.create_task(
                self._safe_search_mysql(query, top_k, trace_id)
            ))
            source_labels.append("mysql")

        # Agent memory
        if not sources or "memory" in (sources or []):
            tasks.append(asyncio.create_task(
                self._safe_search_memory(query, agent_id, top_k, context or {}, trace_id)
            ))
            source_labels.append("memory")

        timeout = self._settings.rag_parallel_timeout_sec
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: List[SearchResult] = []
        queried_sources: List[str] = []
        for label, result in zip(source_labels, gathered):
            if isinstance(result, Exception):
                log.warning(
                    "Source retrieval failed",
                    source=label,
                    error=str(result),
                )
            else:
                all_results.extend(result)
                queried_sources.append(label)

        merged = self._deduplicate(all_results)
        reranked = await self._reranker.rerank(query, merged, top_k=top_k)

        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        log.info(
            "Retrieval complete",
            sources=queried_sources,
            total_candidates=len(all_results),
            reranked=len(reranked),
            latency_ms=elapsed_ms,
        )
        return {
            "results": reranked,
            "sources_queried": queried_sources,
            "latency_ms": elapsed_ms,
        }

    # ------------------------------------------------------------------
    # Per-source helpers
    # ------------------------------------------------------------------

    async def _safe_search_vector(
        self, query_vec: List[float], k: int, trace_id: str
    ) -> List[SearchResult]:
        timeout = self._settings.rag_parallel_timeout_sec
        return await asyncio.wait_for(
            self._vector_store.search(query_vec, k), timeout=timeout
        )

    async def _safe_search_mysql(
        self, query: str, k: int, trace_id: str
    ) -> List[SearchResult]:
        timeout = self._settings.rag_parallel_timeout_sec
        return await asyncio.wait_for(
            self._mysql.search(query, k), timeout=timeout
        )

    async def _safe_search_memory(
        self,
        query: str,
        agent_id: int,
        k: int,
        context: dict,
        trace_id: str,
    ) -> List[SearchResult]:
        timeout = self._settings.rag_parallel_timeout_sec
        return await asyncio.wait_for(
            self._call_memory_service(query, agent_id, k, context, trace_id),
            timeout=timeout,
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, max=10),
        reraise=True,
    )
    async def _call_memory_service(
        self,
        query: str,
        agent_id: int,
        k: int,
        context: dict,
        trace_id: str,
    ) -> List[SearchResult]:
        url = f"{self._settings.memory_service_url}/v1/memory/assemble-prompt"
        payload = {
            "agent_id": agent_id,
            "context": {
                "task_type": context.get("domain", "general"),
                "domain": context.get("domain", ""),
                "recent_messages": [query],
            },
            "tiers": ["short_term", "long_term", "episodic"],
        }
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.post(
                url, json=payload, headers={"x-request-id": trace_id}
            )
            resp.raise_for_status()
            data = resp.json()

        prompt = data.get("system_prompt", "")
        if not prompt:
            return []
        return [
            SearchResult(
                id=f"memory_{agent_id}_{trace_id}",
                content=prompt,
                score=1.0,
                source="memory",
                metadata={"agent_id": agent_id, "sources": data.get("sources", {})},
            )
        ]

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    @staticmethod
    def _deduplicate(results: List[SearchResult]) -> List[SearchResult]:
        seen: set[str] = set()
        unique: List[SearchResult] = []
        for r in results:
            key = r.content[:_DEDUP_SIMILARITY_CHARS].strip()
            if key not in seen:
                seen.add(key)
                unique.append(r)
        return unique
