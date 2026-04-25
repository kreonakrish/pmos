"""Sentence-transformers embedding wrapper.

Loads the model lazily so the service can boot even when the model files are
missing (e.g. air-gapped CI). Encoding runs in a thread pool because
SentenceTransformer is synchronous and CPU-bound.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional

from app.config import settings
from app.utils.logger import logger

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="translator-embedder")


class Embedder:
    """Async wrapper around SentenceTransformer.

    Exposes ``available()`` so callers (e.g. the promote-example route) can
    skip embedding gracefully when the model couldn't load.
    """

    def __init__(self, model_name: Optional[str] = None) -> None:
        self._model_name = model_name or settings.embedding_model
        self._model: Optional[object] = None
        self._available: Optional[bool] = None

    def _try_load(self) -> bool:
        if self._model is not None:
            return True
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore

            logger.info(
                "Loading embedding model",
                layer="adapter",
                model=self._model_name,
            )
            self._model = SentenceTransformer(self._model_name)
            return True
        except Exception as exc:
            logger.warning(
                "Embedding model unavailable — embedder will be in degraded mode",
                layer="adapter",
                model=self._model_name,
                error=str(exc),
            )
            self._model = None
            return False

    def available(self) -> bool:
        if self._available is None:
            self._available = self._try_load()
        return bool(self._available)

    def _encode_sync(self, text: str) -> List[float]:
        if not self._try_load():
            raise RuntimeError("Embedder unavailable")
        vec = self._model.encode(text, normalize_embeddings=True)  # type: ignore[union-attr]
        return [float(x) for x in vec.tolist()]

    async def embed(self, text: str) -> List[float]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self._encode_sync, text)

    def dimension(self) -> Optional[int]:
        """Return the model's vector size, loading it if necessary.

        ``None`` if the model couldn't be loaded — callers should fall back to
        the contract default (TRANSLATION_EXAMPLES_DIM).
        """
        if not self._try_load():
            return None
        try:
            return int(self._model.get_sentence_embedding_dimension())  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Embedder dimension probe failed",
                layer="adapter",
                model=self._model_name,
                error=str(exc),
            )
            return None

    async def health_check(self) -> bool:
        # available() may load synchronously — run in thread to keep loop free.
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_executor, self.available)
