import re
import time
import uuid
from typing import Any, Dict, List, Optional

from app.adapters.base import VectorStoreAdapter
from app.adapters.faiss_adapter import FAISSAdapter
from app.adapters.mysql_fulltext import MySQLFullTextAdapter
from app.utils.chunker import DocumentChunker
from app.utils.embedding import embed_texts
from app.utils.logger import get_logger

logger = get_logger(layer="ingestion")


class IngestionService:
    """
    Document ingestion pipeline:
      1. Clean content
      2. Chunk
      3. Embed (batch)
      4. Upsert to primary vector store
      5. Upsert to local FAISS (mirror)
      6. Insert metadata to MySQL
    """

    def __init__(
        self,
        vector_store: VectorStoreAdapter,
        faiss_adapter: FAISSAdapter,
        mysql_adapter: MySQLFullTextAdapter,
        settings,
    ) -> None:
        self._vector_store = vector_store
        self._faiss = faiss_adapter
        self._mysql = mysql_adapter
        self._chunker = DocumentChunker()
        self._settings = settings

    async def ingest_document(
        self,
        content: str,
        filename: str,
        agent_id: int = 0,
        team_id: str = "",
        conversation_id: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        options = options or {}
        trace_id = trace_id or str(uuid.uuid4())
        log = logger.with_trace(trace_id)
        start_ms = int(time.monotonic() * 1000)

        document_id = str(uuid.uuid4())
        strategy = options.get("chunk_strategy", "fixed")
        chunk_size = options.get("chunk_size") or self._settings.rag_chunk_size
        chunk_overlap = options.get("chunk_overlap") or self._settings.rag_chunk_overlap
        embedding_model = options.get("embedding_model") or self._settings.embedding_model

        # 1. Clean
        cleaned = self._clean(content)

        # 2. Chunk
        chunks = self._chunker.chunk(
            cleaned,
            strategy=strategy,
            chunk_size=chunk_size,
            overlap=chunk_overlap,
        )
        log.info("Document chunked", doc_id=document_id, chunks=len(chunks),
                 strategy=strategy, chunk_size=chunk_size, embedding_model=embedding_model)

        if not chunks:
            log.warning("No chunks produced", doc_id=document_id)
            return {"chunks_indexed": 0, "document_id": document_id}

        # 3. Embed
        vectors = await embed_texts(embedding_model, chunks)

        # 4. Upsert to primary vector store
        # 5. Upsert to local FAISS (mirror)
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            chunk_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}_{i}"))
            metadata = {
                "content": chunk,
                "document_id": document_id,
                "chunk_index": i,
                "filename": filename,
                "agent_id": agent_id,
                "team_id": team_id,
                "conversation_id": conversation_id or "",
            }
            await self._vector_store.upsert(chunk_id, vec, metadata)
            await self._faiss.upsert(chunk_id, vec, {**metadata, "_collection": "documents"})

        # 6. Insert metadata to MySQL (full content for FTS)
        await self._mysql.insert_document(
            doc_id=document_id,
            content=cleaned,
            filename=filename,
            team_id=team_id,
            agent_id=agent_id,
            conversation_id=conversation_id,
        )

        elapsed_ms = int(time.monotonic() * 1000) - start_ms
        log.info(
            "Ingestion complete",
            doc_id=document_id,
            chunks=len(chunks),
            latency_ms=elapsed_ms,
        )
        return {"chunks_indexed": len(chunks), "document_id": document_id}

    # ------------------------------------------------------------------

    @staticmethod
    def _clean(text: str) -> str:
        """Remove null bytes, excessive whitespace, and control chars."""
        text = text.replace("\x00", "")
        text = re.sub(r"[\r\n]{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text)
        return text.strip()
