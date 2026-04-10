from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SearchResult:
    id: str
    content: str
    score: float
    source: str
    metadata: dict = field(default_factory=dict)


class VectorStoreAdapter(ABC):
    """Abstract base class for all vector store backends."""

    @abstractmethod
    async def upsert(self, id: str, vector: List[float], metadata: dict) -> None:
        """Insert or update a vector with associated metadata."""
        ...

    @abstractmethod
    async def search(
        self,
        query_vector: List[float],
        k: int,
        filters: Optional[dict] = None,
    ) -> List[SearchResult]:
        """Return the top-k nearest neighbours for query_vector."""
        ...

    @abstractmethod
    async def delete(self, id: str) -> None:
        """Remove a vector by ID."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the backend is reachable and operational."""
        ...

    @abstractmethod
    async def create_collection(self, name: str, dimension: int) -> None:
        """Create a new collection / index if it does not already exist."""
        ...
