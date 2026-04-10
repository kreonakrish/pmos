import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import List

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

from app.utils.logger import get_logger

logger = get_logger(layer="embedding")

_executor = ThreadPoolExecutor(max_workers=2)
_model_cache: dict[str, SentenceTransformer] = {}


def _load_model(model_name: str) -> SentenceTransformer:
    if model_name not in _model_cache:
        logger.info("Loading embedding model", model=model_name)
        _model_cache[model_name] = SentenceTransformer(model_name)
    return _model_cache[model_name]


def _encode_sync(model_name: str, texts: List[str]) -> List[List[float]]:
    model = _load_model(model_name)
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


async def embed_texts(model_name: str, texts: List[str]) -> List[List[float]]:
    """Embed a batch of texts asynchronously (CPU work in thread pool)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, _encode_sync, model_name, texts)


async def embed_query(model_name: str, query: str) -> List[float]:
    """Embed a single query string."""
    results = await embed_texts(model_name, [query])
    return results[0]
