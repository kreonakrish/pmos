import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List

try:
    from sentence_transformers import CrossEncoder
except ImportError:
    CrossEncoder = None

from app.adapters.base import SearchResult
from app.utils.logger import get_logger

logger = get_logger(layer="reranker")

_executor = ThreadPoolExecutor(max_workers=1)


class Reranker:
    """
    Cross-encoder re-ranker.  CPU-bound scoring is offloaded to a thread pool
    to keep the asyncio event loop unblocked.
    """

    def __init__(self, model_name: str) -> None:
        logger.info("Loading cross-encoder model", model=model_name)
        self._model = CrossEncoder(model_name)

    def _predict_sync(self, pairs: List[tuple]) -> List[float]:
        scores = self._model.predict(pairs)
        return [float(s) for s in scores]

    async def rerank(
        self,
        query: str,
        candidates: List[SearchResult],
        top_k: int,
    ) -> List[dict]:
        """
        Score each (query, candidate.content) pair using the cross-encoder.
        Returns top_k results sorted by descending score as plain dicts.
        """
        if not candidates:
            return []

        pairs = [(query, c.content) for c in candidates]
        loop = asyncio.get_event_loop()
        scores = await loop.run_in_executor(_executor, self._predict_sync, pairs)

        ranked = sorted(zip(candidates, scores), key=lambda x: x[1], reverse=True)
        return [
            {
                "content": c.content,
                "score": float(s),
                "source": c.source,
                "metadata": c.metadata,
            }
            for c, s in ranked[:top_k]
        ]
