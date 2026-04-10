"""Sentence-transformers embedding wrapper — CPU-bound work runs in a thread pool."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import numpy as np

from app.utils.logger import get_logger

logger = get_logger()

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="embedding")


class EmbeddingService:
    """Wraps SentenceTransformer to provide async embedding in a shared thread pool."""

    def __init__(self, model_name: str):
        self._model_name = model_name
        self._model: Optional[object] = None  # lazy-loaded

    def _load_model(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore
            logger.info("Loading embedding model", model=self._model_name, layer="utils")
            self._model = SentenceTransformer(self._model_name)

    def _encode_sync(self, text: str) -> np.ndarray:
        self._load_model()
        result = self._model.encode(text, normalize_embeddings=True)  # type: ignore[union-attr]
        return np.array(result, dtype=np.float32)

    def _encode_batch_sync(self, texts: list[str]) -> np.ndarray:
        self._load_model()
        result = self._model.encode(texts, normalize_embeddings=True, batch_size=32)  # type: ignore[union-attr]
        return np.array(result, dtype=np.float32)

    async def embed(self, text: str) -> np.ndarray:
        """Embed a single text string. Returns normalised float32 vector."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._encode_sync, text)

    async def embed_batch(self, texts: list[str]) -> np.ndarray:
        """Embed multiple texts in a single model call."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._encode_batch_sync, texts)


# Module-level singleton — instantiated lazily via get_embedding_service()
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service(model_name: str | None = None) -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        from app.config import settings
        _embedding_service = EmbeddingService(model_name or settings.embedding_model)
    return _embedding_service
