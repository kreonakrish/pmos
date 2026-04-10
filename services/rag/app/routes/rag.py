import time
import uuid

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from prometheus_client import Counter, Histogram

from pydantic import BaseModel
from app.models.rag import IngestRequest, IngestResponse, QueryRequest, QueryResponse, RetrievedResult
from app.utils.file_parser import parse_file
from typing import Any, Dict, List, Optional
from app.utils.logger import get_logger

logger = get_logger(layer="router")

router = APIRouter(prefix="/v1/rag")

# ---------------------------------------------------------------------------
# Prometheus metrics
# ---------------------------------------------------------------------------
REQUEST_TOTAL = Counter(
    "request_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_DURATION = Histogram(
    "request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
)
RAG_SOURCES_QUERIED = Counter(
    "rag_sources_queried",
    "Count of RAG sources queried",
    ["source"],
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/query", response_model=QueryResponse)
async def query_rag(body: QueryRequest, request: Request) -> QueryResponse:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    log = logger.with_trace(trace_id)
    start = time.monotonic()

    try:
        retrieval_svc = request.app.state.retrieval_service
        settings = request.app.state.settings
        top_k = body.top_k or settings.rag_top_k

        result = await retrieval_svc.retrieve(
            query=body.query,
            agent_id=body.agent_id,
            top_k=top_k,
            sources=body.sources,
            context=body.context.model_dump() if body.context else {},
            trace_id=trace_id,
        )

        for src in result["sources_queried"]:
            RAG_SOURCES_QUERIED.labels(source=src).inc()

        duration = time.monotonic() - start
        REQUEST_TOTAL.labels(method="POST", path="/v1/rag/query", status="200").inc()
        REQUEST_DURATION.labels(method="POST", path="/v1/rag/query").observe(duration)

        log.info("RAG query served", latency_ms=result["latency_ms"], top_k=top_k)

        return QueryResponse(
            results=[RetrievedResult(**r) for r in result["results"]],
            sources_queried=result["sources_queried"],
            latency_ms=result["latency_ms"],
            trace_id=trace_id,
        )

    except Exception as exc:
        REQUEST_TOTAL.labels(method="POST", path="/v1/rag/query", status="500").inc()
        log.error("RAG query failed", error=str(exc))
        raise HTTPException(status_code=500, detail={"error": str(exc), "code": "QUERY_ERROR", "trace_id": trace_id})


@router.post("/ingest", response_model=IngestResponse)
async def ingest_document(body: IngestRequest, request: Request) -> IngestResponse:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    log = logger.with_trace(trace_id)
    start = time.monotonic()

    try:
        ingestion_svc = request.app.state.ingestion_service

        result = await ingestion_svc.ingest_document(
            content=body.content,
            filename=body.filename,
            agent_id=body.agent_id,
            team_id=body.team_id,
            conversation_id=body.conversation_id,
            options={
                "chunk_strategy": body.chunk_strategy,
                "chunk_size": body.chunk_size,
                "chunk_overlap": body.chunk_overlap,
                "embedding_model": body.embedding_model,
            },
            trace_id=trace_id,
        )

        duration = time.monotonic() - start
        REQUEST_TOTAL.labels(method="POST", path="/v1/rag/ingest", status="200").inc()
        REQUEST_DURATION.labels(method="POST", path="/v1/rag/ingest").observe(duration)

        log.info(
            "Ingest complete",
            doc_id=result["document_id"],
            chunks=result["chunks_indexed"],
            latency_ms=int(duration * 1000),
        )

        return IngestResponse(
            chunks_indexed=result["chunks_indexed"],
            document_id=result["document_id"],
            trace_id=trace_id,
        )

    except Exception as exc:
        REQUEST_TOTAL.labels(method="POST", path="/v1/rag/ingest", status="500").inc()
        log.error("Ingest failed", error=str(exc))
        raise HTTPException(status_code=500, detail={"error": str(exc), "code": "INGEST_ERROR", "trace_id": trace_id})


@router.post("/upload", response_model=IngestResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    chunk_strategy: str = Form("sentence"),
    chunk_size: int = Form(500),
    chunk_overlap: int = Form(50),
    embedding_model: Optional[str] = Form(None),
    team_id: str = Form(""),
    agent_id: int = Form(0),
    conversation_id: Optional[str] = Form(None),
) -> IngestResponse:
    """Upload a binary file (PDF, DOCX, XLSX, HTML, CSV, TXT, etc.) for RAG ingestion."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    log = logger.with_trace(trace_id)
    start = time.monotonic()

    try:
        raw_bytes = await file.read()
        filename = file.filename or "unknown"
        mime_type = file.content_type or ""

        log.info("File upload received", filename=filename, size=len(raw_bytes), mime_type=mime_type)

        # Parse binary content to text
        text_content = parse_file(raw_bytes, filename, mime_type)

        if not text_content.strip():
            raise HTTPException(status_code=400, detail={
                "error": "No text could be extracted from the file",
                "code": "EMPTY_CONTENT", "trace_id": trace_id,
            })

        ingestion_svc = request.app.state.ingestion_service
        result = await ingestion_svc.ingest_document(
            content=text_content,
            filename=filename,
            agent_id=agent_id,
            team_id=team_id,
            conversation_id=conversation_id,
            options={
                "chunk_strategy": chunk_strategy,
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "embedding_model": embedding_model,
            },
            trace_id=trace_id,
        )

        duration = time.monotonic() - start
        log.info("File upload ingested", doc_id=result["document_id"],
                 chunks=result["chunks_indexed"], latency_ms=int(duration * 1000))

        return IngestResponse(
            chunks_indexed=result["chunks_indexed"],
            document_id=result["document_id"],
            trace_id=trace_id,
        )

    except HTTPException:
        raise
    except Exception as exc:
        log.error("File upload ingestion failed", error=str(exc))
        raise HTTPException(status_code=500, detail={
            "error": str(exc), "code": "UPLOAD_ERROR", "trace_id": trace_id,
        })


@router.get("/config")
async def get_rag_config(request: Request) -> Dict[str, Any]:
    """Return current RAG pipeline configuration for the UI."""
    from app.config import settings
    return {
        "embedding_model": settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "chunk_size": settings.rag_chunk_size,
        "chunk_overlap": settings.rag_chunk_overlap,
        "chunk_strategies": ["fixed", "sentence", "paragraph"],
        "available_models": [
            "sentence-transformers/all-mpnet-base-v2",
            "sentence-transformers/all-MiniLM-L6-v2",
            "sentence-transformers/all-MiniLM-L12-v2",
            "sentence-transformers/paraphrase-MiniLM-L6-v2",
        ],
        "vector_store_backend": settings.vector_store_backend,
        "top_k": settings.rag_top_k,
        "reranker_model": settings.reranker_model,
    }


@router.get("/documents")
async def list_documents(request: Request) -> Dict[str, Any]:
    """List all ingested documents from MySQL."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    log = logger.with_trace(trace_id)
    try:
        mysql_adapter = request.app.state.mysql_adapter
        docs = await mysql_adapter.list_documents()
        log.info("Documents listed", count=len(docs))
        return {"documents": docs, "trace_id": trace_id}
    except Exception as exc:
        log.error("Document list failed", error=str(exc))
        raise HTTPException(status_code=500, detail={"error": str(exc), "code": "LIST_ERROR", "trace_id": trace_id})


@router.get("/documents/{doc_id}/chunks")
async def get_document_chunks(doc_id: str, request: Request) -> Dict[str, Any]:
    """Return the chunks for a given document from the vector store."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    log = logger.with_trace(trace_id)
    try:
        mysql_adapter = request.app.state.mysql_adapter
        chunks = await mysql_adapter.get_document_chunks(doc_id)
        log.info("Chunks retrieved", doc_id=doc_id, count=len(chunks))
        return {"chunks": chunks, "doc_id": doc_id, "trace_id": trace_id}
    except Exception as exc:
        log.error("Chunk retrieval failed", error=str(exc))
        raise HTTPException(status_code=500, detail={"error": str(exc), "code": "CHUNKS_ERROR", "trace_id": trace_id})


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str, request: Request) -> Dict[str, Any]:
    """Fetch single document metadata from MySQL."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    log = logger.with_trace(trace_id)
    try:
        mysql_adapter = request.app.state.mysql_adapter
        doc = await mysql_adapter.get_document(doc_id)
        if doc is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "Document not found", "code": "NOT_FOUND", "trace_id": trace_id},
            )
        log.info("Document retrieved", doc_id=doc_id)
        return {"document": doc, "trace_id": trace_id}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Document retrieval failed", error=str(exc))
        raise HTTPException(status_code=500, detail={"error": str(exc), "code": "GET_DOC_ERROR", "trace_id": trace_id})


class ReindexRequest(BaseModel):
    chunk_strategy: str = "sentence"
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    embedding_model: Optional[str] = None


@router.post("/documents/{doc_id}/reindex")
async def reindex_document(doc_id: str, request: Request, body: Optional[ReindexRequest] = None) -> Dict[str, Any]:
    """Re-ingest a document with new pipeline config: chunk strategy, size, model."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    log = logger.with_trace(trace_id)
    start = time.monotonic()
    body = body or ReindexRequest()

    try:
        mysql_adapter = request.app.state.mysql_adapter
        doc = await mysql_adapter.get_document(doc_id)
        if doc is None:
            raise HTTPException(
                status_code=404,
                detail={"error": "Document not found", "code": "NOT_FOUND", "trace_id": trace_id},
            )

        ingestion_svc = request.app.state.ingestion_service

        # Delete old document first
        await mysql_adapter.delete_document(doc_id)

        # Re-ingest with new pipeline config
        result = await ingestion_svc.ingest_document(
            content=doc.get("content", ""),
            filename=doc.get("filename", "unknown"),
            agent_id=doc.get("agent_id", 0),
            team_id=doc.get("team_id", ""),
            conversation_id=doc.get("conversation_id"),
            options={
                "chunk_strategy": body.chunk_strategy,
                "chunk_size": body.chunk_size,
                "chunk_overlap": body.chunk_overlap,
                "embedding_model": body.embedding_model,
            },
            trace_id=trace_id,
        )

        duration = time.monotonic() - start
        log.info(
            "Document reindexed",
            doc_id=doc_id,
            new_doc_id=result["document_id"],
            chunks=result["chunks_indexed"],
            latency_ms=int(duration * 1000),
        )

        return {
            "reindexed": True,
            "old_doc_id": doc_id,
            "new_document_id": result["document_id"],
            "chunks_indexed": result["chunks_indexed"],
            "trace_id": trace_id,
        }

    except HTTPException:
        raise
    except Exception as exc:
        log.error("Document reindex failed", error=str(exc))
        raise HTTPException(status_code=500, detail={"error": str(exc), "code": "REINDEX_ERROR", "trace_id": trace_id})


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, request: Request) -> Dict[str, Any]:
    """Delete a document and its chunks from all stores."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    log = logger.with_trace(trace_id)
    try:
        mysql_adapter = request.app.state.mysql_adapter
        await mysql_adapter.delete_document(doc_id)
        log.info("Document deleted", doc_id=doc_id)
        return {"deleted": True, "doc_id": doc_id, "trace_id": trace_id}
    except Exception as exc:
        log.error("Document deletion failed", error=str(exc))
        raise HTTPException(status_code=500, detail={"error": str(exc), "code": "DELETE_ERROR", "trace_id": trace_id})
