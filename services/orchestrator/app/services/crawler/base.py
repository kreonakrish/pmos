"""Base types for the metadata crawler framework.

Every source-type crawler (MySQLCrawler, SnowflakeCrawler, ...) subclasses
BaseCrawler and returns a CrawlResult — a list of CrawledAssets, each with a
list of CrawledColumns. The crawler framework is sync-I/O on purpose; LLM
mapping and Neo4j writes happen in a separate async step so the crawler code
stays readable and testable.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CrawledColumn:
    """One column on a crawled asset. Sample values are optional and may be
    skipped in restricted environments."""
    name: str
    data_type: str
    nullable: bool
    ordinal: int
    is_pk: bool = False
    is_fk: bool = False
    fk_references: Optional[str] = None  # "schema.table.column"
    default_value: Optional[str] = None
    comment: Optional[str] = None
    sample_values: List[Any] = field(default_factory=list)


@dataclass
class CrawledAsset:
    """A single table, view, procedure, file, or report."""
    source_name: str                  # logical source id, e.g. "mysql_local"
    source_uri: str                   # e.g. "mysql://host:3306/pmos_servicing"
    asset_type: str                   # 'TABLE', 'VIEW', 'PROCEDURE', 'FILE', 'REPORT'
    schema_name: Optional[str]
    asset_name: str                   # bare name ("loans"), not qualified
    fully_qualified: str              # "pmos_servicing.loans"
    row_count: Optional[int] = None
    comment: Optional[str] = None
    columns: List[CrawledColumn] = field(default_factory=list)


@dataclass
class CrawlResult:
    source_name: str
    source_type: str
    source_uri: str
    assets: List[CrawledAsset] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def total_columns(self) -> int:
        return sum(len(a.columns) for a in self.assets)


class BaseCrawler(ABC):
    """Abstract crawler base. Subclasses implement `discover`."""

    source_type: str = "UNKNOWN"

    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config or {}
        self.connection = self.config.get("connection", {}) or {}
        self.options = self.config.get("options", {}) or {}

    @abstractmethod
    def discover(self) -> CrawlResult:
        """Connect to the source, enumerate assets and columns, return the
        full CrawlResult. Must not raise on partial failure — append to
        result.errors instead and keep going.
        """
        raise NotImplementedError

    # Common helper: slugify a source into a stable logical id.
    @staticmethod
    def _source_name_from(source_type: str, host: str, database: str) -> str:
        safe = (host or "local").replace(".", "_").replace(":", "_")
        if database:
            safe += f"_{database}"
        return f"{source_type.lower()}_{safe}"
