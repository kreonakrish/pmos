from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class QueryContext(BaseModel):
    task_id: Optional[str] = None
    domain: Optional[str] = None


class QueryRequest(BaseModel):
    query: str
    agent_id: int
    top_k: Optional[int] = None  # falls back to config default
    sources: Optional[List[str]] = None  # filter: qdrant/faiss/mysql/memory/pinecone/weaviate
    context: Optional[QueryContext] = None


class IngestRequest(BaseModel):
    content: str
    filename: str
    mime_type: str = "text/plain"
    team_id: str = ""
    agent_id: int = 0
    conversation_id: Optional[str] = None
    chunk_strategy: str = "fixed"  # fixed | sentence | paragraph
    chunk_size: Optional[int] = None  # override config default
    chunk_overlap: Optional[int] = None  # override config default
    embedding_model: Optional[str] = None  # override config default


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class RetrievedResult(BaseModel):
    content: str
    score: float
    source: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QueryResponse(BaseModel):
    results: List[RetrievedResult]
    sources_queried: List[str]
    latency_ms: int
    trace_id: str


class IngestResponse(BaseModel):
    chunks_indexed: int
    document_id: str
    trace_id: str


class HealthResponse(BaseModel):
    status: str
    service: str = "rag"
    checks: Dict[str, bool] = Field(default_factory=dict)
