"""Neo4j metadata crawler.

Introspects a Neo4j database — enumerating node labels, relationship types,
property keys, and sample property values — and shapes the result onto the
existing relational catalog model so all downstream code (capability
negotiation, MAPS_TO mapping, dataset binding) keeps working unchanged:

  Node label       → CrawledAsset(asset_type='NODE_LABEL'),  property → CrawledColumn
  Relationship type→ CrawledAsset(asset_type='RELATIONSHIP'),property → CrawledColumn

The same AuraDB instance often hosts BOTH the PMOS ontology graph (BusinessEntity,
DataAsset, Tool, ...) AND business data (Customer, Loan, ...). The crawler MUST
NOT introspect the ontology system labels, so a default deny-list filters them
out before any sampling. Users can extend it via options.excluded_labels.

config shape (stored in crawlers.connection / crawlers.options):

    {
      "connection": {
        "uri": "neo4j+s://xxxx.databases.neo4j.io",   # falls back to NEO4J_URI env
        "user": "neo4j",                              # falls back to NEO4J_USER env
        "password": "...",                            # falls back to NEO4J_PASSWORD env
        "database": "neo4j"                           # falls back to NEO4J_DATABASE env
      },
      "options": {
        "sample_rows": 5,
        "skip_sensitive": true,
        "include_relationships": true,
        "excluded_labels": ["MyExtraLabel"],          # appended to default deny-list
        "excluded_rel_types": ["LEGACY_REL"]
      }
    }
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from neo4j import GraphDatabase

from app.services.crawler.base import (
    BaseCrawler,
    CrawledAsset,
    CrawledColumn,
    CrawlResult,
)

logger = logging.getLogger("pmos.crawler.neo4j")

SENSITIVE_PATTERNS = re.compile(
    r"(ssn|password|secret|token|api_?key|credit_?card|card_?num|cvv|pin|hash)",
    re.IGNORECASE,
)

# Labels that belong to the PMOS ontology / governance / execution graph and
# must NEVER be surfaced as business assets. The user data (Customer, Loan, …)
# co-exists with these in the same AuraDB.
DEFAULT_EXCLUDED_LABELS: Set[str] = {
    # Ontology
    "BusinessDomain", "BusinessEntity", "BusinessAttribute",
    "DataSource", "DataAsset", "DataColumn",
    # Tools / agents / teams
    "Tool", "Agent", "Team", "ToolEndpoint",
    "AIAgent", "AIInteraction",
    "AgentCapabilityNode", "AgentInteraction",
    # Reports
    "Report", "ReportDataset",
    # Execution / SOP graph
    "TaskNode", "TaskGraph", "Episode", "ExecutionEpisode",
    "SOPNode",
    # Governance
    "AuditorIssue", "SynonymProposal", "AuditEvent",
    # Internal indexes / housekeeping
    "_Neo4jMigration",
}

DEFAULT_EXCLUDED_REL_TYPES: Set[str] = {
    "HAS_ENTITY", "HAS_ATTRIBUTE", "HAS_ASSET", "HAS_COLUMN",
    "MAPS_TO", "REFERENCES", "RELATED_TO",
    "ACCESSES", "USES_ATTRIBUTE", "HAS_DATASET", "RUNS_ON",
    "BELONGS_TO_TEAM", "OWNS_TOOL",
    "TRIGGERED", "EMITTED", "DECOMPOSED_TO",
}


def _infer_data_type(samples: List[Any]) -> str:
    """Coarse type inference from the first non-null sample. Mirrors the
    'string'/'integer'/'float'/'boolean' shape MySQL crawler emits."""
    for v in samples:
        if v is None:
            continue
        if isinstance(v, bool):
            return "boolean"
        if isinstance(v, int):
            return "integer"
        if isinstance(v, float):
            return "float"
        if isinstance(v, list):
            return "list"
        if isinstance(v, dict):
            return "map"
        # Neo4j temporal types expose isoformat()
        if hasattr(v, "isoformat"):
            return "datetime"
        return "string"
    return "unknown"


def _to_jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, list):
        return [_to_jsonable(x) for x in v]
    return str(v)


class Neo4jCrawler(BaseCrawler):
    source_type = "NEO4J"

    def _connect(self):
        conn_cfg = dict(self.connection)
        uri = conn_cfg.get("uri") or os.environ.get("NEO4J_URI", "")
        user = conn_cfg.get("user") or os.environ.get("NEO4J_USER", "neo4j")
        password = conn_cfg.get("password") or os.environ.get("NEO4J_PASSWORD", "")
        if not uri:
            raise RuntimeError("NEO4J uri missing — set connection.uri or NEO4J_URI env")
        return GraphDatabase.driver(uri, auth=(user, password))

    def _database(self) -> Optional[str]:
        return (
            self.connection.get("database")
            or os.environ.get("NEO4J_DATABASE")
            or None
        )

    def discover(self) -> CrawlResult:
        sample_rows = int(self.options.get("sample_rows", 5))
        skip_sensitive = bool(self.options.get("skip_sensitive", True))
        include_rels = bool(self.options.get("include_relationships", True))

        excluded_labels = set(DEFAULT_EXCLUDED_LABELS)
        for extra in (self.options.get("excluded_labels") or []):
            excluded_labels.add(str(extra))

        excluded_rels = set(DEFAULT_EXCLUDED_REL_TYPES)
        for extra in (self.options.get("excluded_rel_types") or []):
            excluded_rels.add(str(extra))

        uri = self.connection.get("uri") or os.environ.get("NEO4J_URI", "neo4j://unknown")
        database = self._database() or "neo4j"
        host = re.sub(r"^[a-z+]+://", "", uri).split("/")[0]
        source_uri = f"neo4j://{host}/{database}"
        source_name = self._source_name_from(self.source_type, host, database)

        result = CrawlResult(
            source_name=source_name,
            source_type=self.source_type,
            source_uri=source_uri,
        )

        try:
            driver = self._connect()
        except Exception as exc:
            result.errors.append(f"connect: {exc}")
            return result

        try:
            with driver.session(database=database) as session:
                labels = self._discover_labels(session, excluded_labels, result)
                logger.info(
                    "Neo4j labels discovered",
                    extra={"count": len(labels), "source": source_name},
                )

                for label in labels:
                    asset = self._crawl_label(
                        session=session,
                        label=label,
                        source_name=source_name,
                        source_uri=source_uri,
                        sample_rows=sample_rows,
                        skip_sensitive=skip_sensitive,
                        result=result,
                    )
                    if asset is not None:
                        result.assets.append(asset)

                if include_rels:
                    rels = self._discover_rel_triples(session, labels, excluded_rels, result)
                    logger.info(
                        "Neo4j relationship triples discovered",
                        extra={"count": len(rels), "source": source_name},
                    )
                    for src_label, rel_type, tgt_label in rels:
                        asset = self._crawl_relationship(
                            session=session,
                            src_label=src_label,
                            rel_type=rel_type,
                            tgt_label=tgt_label,
                            source_name=source_name,
                            source_uri=source_uri,
                            sample_rows=sample_rows,
                            skip_sensitive=skip_sensitive,
                            result=result,
                        )
                        if asset is not None:
                            result.assets.append(asset)
        except Exception as exc:
            result.errors.append(f"crawler error: {exc}")
        finally:
            try:
                driver.close()
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------
    # Label discovery
    # ------------------------------------------------------------------
    def _discover_labels(
        self,
        session,
        excluded: Set[str],
        result: CrawlResult,
    ) -> List[str]:
        try:
            rows = session.run("CALL db.labels() YIELD label RETURN label").data()
        except Exception as exc:
            result.errors.append(f"db.labels(): {exc}")
            return []
        labels = [r["label"] for r in rows or [] if r.get("label")]
        return [lbl for lbl in labels if lbl not in excluded and not lbl.startswith("_")]

    # ------------------------------------------------------------------
    # Per-label asset
    # ------------------------------------------------------------------
    def _crawl_label(
        self,
        session,
        label: str,
        source_name: str,
        source_uri: str,
        sample_rows: int,
        skip_sensitive: bool,
        result: CrawlResult,
    ) -> Optional[CrawledAsset]:
        # Row count + property keys (all in one query — uses APOC-free Cypher).
        try:
            count_row = session.run(
                f"MATCH (n:`{label}`) RETURN count(n) AS c"
            ).single()
            row_count = int(count_row["c"]) if count_row and count_row["c"] is not None else 0
        except Exception as exc:
            result.errors.append(f"count {label}: {exc}")
            return None

        if row_count == 0:
            return None  # phantom label

        try:
            prop_rows = session.run(
                f"""
                MATCH (n:`{label}`)
                WITH n LIMIT 200
                UNWIND keys(n) AS k
                RETURN DISTINCT k AS prop
                """
            ).data()
        except Exception as exc:
            result.errors.append(f"props {label}: {exc}")
            return None

        properties = sorted({r["prop"] for r in prop_rows or [] if r.get("prop")})

        asset = CrawledAsset(
            source_name=source_name,
            source_uri=source_uri,
            asset_type="NODE_LABEL",
            schema_name="graph",
            asset_name=label,
            fully_qualified=f"graph.{label}",
            row_count=row_count,
        )

        for ord_, prop in enumerate(properties):
            samples: List[Any] = []
            if sample_rows > 0 and not (skip_sensitive and SENSITIVE_PATTERNS.search(prop)):
                try:
                    sample_data = session.run(
                        f"""
                        MATCH (n:`{label}`)
                        WHERE n.`{prop}` IS NOT NULL
                        RETURN DISTINCT n.`{prop}` AS v
                        LIMIT {int(sample_rows)}
                        """
                    ).data()
                    samples = [_to_jsonable(r["v"]) for r in sample_data or []]
                except Exception as exc:
                    result.errors.append(f"sample {label}.{prop}: {exc}")

            asset.columns.append(CrawledColumn(
                name=prop,
                data_type=_infer_data_type(samples),
                nullable=True,
                ordinal=ord_,
                is_pk=False,
                is_fk=False,
                fk_references=None,
                sample_values=samples,
            ))

        return asset

    # ------------------------------------------------------------------
    # Relationship discovery
    # ------------------------------------------------------------------
    def _discover_rel_triples(
        self,
        session,
        live_labels: List[str],
        excluded_rels: Set[str],
        result: CrawlResult,
    ) -> List[Tuple[str, str, str]]:
        """Enumerate (src_label, rel_type, tgt_label) triples that actually
        exist in the data. Uses one query per rel type — fine for the small
        number of rel types in business graphs."""
        try:
            type_rows = session.run(
                "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
            ).data()
        except Exception as exc:
            result.errors.append(f"db.relationshipTypes(): {exc}")
            return []

        live_set = set(live_labels)
        triples: List[Tuple[str, str, str]] = []
        for r in type_rows or []:
            rt = r.get("relationshipType")
            if not rt or rt in excluded_rels:
                continue
            try:
                rows = session.run(
                    f"""
                    MATCH (s)-[r:`{rt}`]->(t)
                    WITH labels(s) AS sl, labels(t) AS tl LIMIT 500
                    UNWIND sl AS s_label
                    UNWIND tl AS t_label
                    RETURN DISTINCT s_label, t_label
                    """
                ).data()
            except Exception as exc:
                result.errors.append(f"rel scan {rt}: {exc}")
                continue
            for row in rows or []:
                s_lbl, t_lbl = row.get("s_label"), row.get("t_label")
                if s_lbl in live_set and t_lbl in live_set:
                    triples.append((s_lbl, rt, t_lbl))
        return triples

    def _crawl_relationship(
        self,
        session,
        src_label: str,
        rel_type: str,
        tgt_label: str,
        source_name: str,
        source_uri: str,
        sample_rows: int,
        skip_sensitive: bool,
        result: CrawlResult,
    ) -> Optional[CrawledAsset]:
        asset_name = f"{rel_type}__{src_label}_to_{tgt_label}"
        fq = f"graph.{asset_name}"

        try:
            count_row = session.run(
                f"""
                MATCH (:`{src_label}`)-[r:`{rel_type}`]->(:`{tgt_label}`)
                RETURN count(r) AS c
                """
            ).single()
            row_count = int(count_row["c"]) if count_row and count_row["c"] is not None else 0
        except Exception as exc:
            result.errors.append(f"rel count {asset_name}: {exc}")
            return None
        if row_count == 0:
            return None

        try:
            prop_rows = session.run(
                f"""
                MATCH (:`{src_label}`)-[r:`{rel_type}`]->(:`{tgt_label}`)
                WITH r LIMIT 200
                UNWIND keys(r) AS k
                RETURN DISTINCT k AS prop
                """
            ).data()
        except Exception as exc:
            result.errors.append(f"rel props {asset_name}: {exc}")
            prop_rows = []

        properties = sorted({r["prop"] for r in prop_rows or [] if r.get("prop")})

        asset = CrawledAsset(
            source_name=source_name,
            source_uri=source_uri,
            asset_type="RELATIONSHIP",
            schema_name="graph",
            asset_name=asset_name,
            fully_qualified=fq,
            row_count=row_count,
            comment=f"({src_label})-[:{rel_type}]->({tgt_label})",
        )

        for ord_, prop in enumerate(properties):
            samples: List[Any] = []
            if sample_rows > 0 and not (skip_sensitive and SENSITIVE_PATTERNS.search(prop)):
                try:
                    sample_data = session.run(
                        f"""
                        MATCH (:`{src_label}`)-[r:`{rel_type}`]->(:`{tgt_label}`)
                        WHERE r.`{prop}` IS NOT NULL
                        RETURN DISTINCT r.`{prop}` AS v
                        LIMIT {int(sample_rows)}
                        """
                    ).data()
                    samples = [_to_jsonable(row["v"]) for row in sample_data or []]
                except Exception as exc:
                    result.errors.append(f"rel sample {asset_name}.{prop}: {exc}")

            asset.columns.append(CrawledColumn(
                name=prop,
                data_type=_infer_data_type(samples),
                nullable=True,
                ordinal=ord_,
                is_pk=False,
                is_fk=False,
                fk_references=None,
                sample_values=samples,
            ))

        return asset
