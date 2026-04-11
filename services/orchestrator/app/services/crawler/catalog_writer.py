"""Writes crawled assets + semantic mappings into Neo4j and the MySQL audit
tables.

Ontology (in Neo4j):

    (:DataSource {source_name, source_type, source_uri})
      -[:HAS_ASSET]-> (:DataAsset {fq_name, asset_type, schema_name, asset_name, row_count, comment})
        -[:HAS_COLUMN]-> (:DataColumn {fq_name, name, data_type, is_pk, is_fk, fk_references, sample_values})

    (:BusinessDomain {name})
      -[:HAS_ENTITY]-> (:BusinessEntity {name, domain})
        -[:HAS_ATTRIBUTE]-> (:BusinessAttribute {name, entity, fq_name})
          -[:MAPS_TO {confidence, status, model_version, created_at}]-> (:DataColumn)

FK relationships from the source are also copied into the graph as:

    (:DataColumn)-[:REFERENCES]->(:DataColumn)
    (:DataAsset)-[:RELATED_TO {via}]->(:DataAsset)

so agents can walk join paths between physical assets.

The MySQL side writes one `semantic_mapping_decisions` row per proposed
column mapping with status='AUTO_ACCEPTED'. The auditor can later flip
these to CONFIRMED / CORRECTED / REJECTED via the review endpoint, at
which point the decision's reward_signal is set and Neo4j is updated
with the auditor's choice.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import mysql.connector

from app.adapters.neo4j_adapter import Neo4jAdapter
from app.config import settings
from app.services.crawler.base import CrawledAsset, CrawlResult
from app.services.crawler.semantic_mapper import AssetProposal

logger = logging.getLogger("pmos.crawler.writer")


@dataclass
class WriteStats:
    assets: int = 0
    columns: int = 0
    mappings: int = 0
    entities: int = 0
    domains: int = 0


class CatalogWriter:
    def __init__(self, neo4j: Neo4jAdapter) -> None:
        self._neo4j = neo4j

    def _mysql(self):
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_db,
            connection_timeout=10,
        )

    # ------------------------------------------------------------------
    # Main entry — writes a whole crawl result plus all proposals
    # ------------------------------------------------------------------
    async def write(
        self,
        crawl: CrawlResult,
        proposals: List[AssetProposal],
        run_id: str,
        crawler_id: str,
        trace_id: str = "",
    ) -> WriteStats:
        stats = WriteStats()

        # 1. DataSource
        await self._neo4j.run_query(
            """
            MERGE (s:DataSource {source_name: $name})
            SET s.source_type = $source_type,
                s.source_uri  = $source_uri,
                s.updated_at  = datetime()
            """,
            {
                "name": crawl.source_name,
                "source_type": crawl.source_type,
                "source_uri": crawl.source_uri,
            },
            trace_id=trace_id,
        )

        # 2. Assets + columns
        for asset in crawl.assets:
            await self._write_asset(crawl, asset, trace_id=trace_id)
            stats.assets += 1
            stats.columns += len(asset.columns)

        # 3. FK edges — after all assets exist
        for asset in crawl.assets:
            for col in asset.columns:
                if col.is_fk and col.fk_references:
                    await self._write_fk_edge(crawl, asset, col, trace_id=trace_id)

        # 4. Semantic mappings + audit rows
        seen_domains = set()
        seen_entities = set()
        for prop in proposals:
            if prop.domain not in seen_domains:
                seen_domains.add(prop.domain)
                stats.domains += 1
            if (prop.domain, prop.entity) not in seen_entities:
                seen_entities.add((prop.domain, prop.entity))
                stats.entities += 1

            await self._write_proposal(
                crawl=crawl,
                proposal=prop,
                run_id=run_id,
                crawler_id=crawler_id,
                trace_id=trace_id,
            )
            stats.mappings += len(prop.columns)

        return stats

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _write_asset(
        self,
        crawl: CrawlResult,
        asset: CrawledAsset,
        trace_id: str = "",
    ) -> None:
        asset_fq = f"{crawl.source_name}::{asset.fully_qualified}"
        await self._neo4j.run_query(
            """
            MATCH (s:DataSource {source_name: $source_name})
            MERGE (a:DataAsset {fq_name: $asset_fq})
            SET a.asset_type  = $asset_type,
                a.schema_name = $schema_name,
                a.asset_name  = $asset_name,
                a.fully_qualified = $fully_qualified,
                a.row_count   = $row_count,
                a.comment     = $comment,
                a.updated_at  = datetime()
            MERGE (s)-[:HAS_ASSET]->(a)
            """,
            {
                "source_name": crawl.source_name,
                "asset_fq": asset_fq,
                "asset_type": asset.asset_type,
                "schema_name": asset.schema_name,
                "asset_name": asset.asset_name,
                "fully_qualified": asset.fully_qualified,
                "row_count": asset.row_count,
                "comment": asset.comment,
            },
            trace_id=trace_id,
        )

        for col in asset.columns:
            col_fq = f"{asset_fq}.{col.name}"
            await self._neo4j.run_query(
                """
                MATCH (a:DataAsset {fq_name: $asset_fq})
                MERGE (c:DataColumn {fq_name: $col_fq})
                SET c.name          = $name,
                    c.data_type     = $data_type,
                    c.nullable      = $nullable,
                    c.is_pk         = $is_pk,
                    c.is_fk         = $is_fk,
                    c.fk_references = $fk_references,
                    c.ordinal       = $ordinal,
                    c.sample_values = $sample_values,
                    c.comment       = $comment,
                    c.updated_at    = datetime()
                MERGE (a)-[:HAS_COLUMN]->(c)
                """,
                {
                    "asset_fq": asset_fq,
                    "col_fq": col_fq,
                    "name": col.name,
                    "data_type": col.data_type,
                    "nullable": col.nullable,
                    "is_pk": col.is_pk,
                    "is_fk": col.is_fk,
                    "fk_references": col.fk_references or "",
                    "ordinal": col.ordinal,
                    "sample_values": [str(v)[:120] for v in (col.sample_values or [])],
                    "comment": col.comment or "",
                },
                trace_id=trace_id,
            )

    async def _write_fk_edge(
        self,
        crawl: CrawlResult,
        asset: CrawledAsset,
        col,
        trace_id: str = "",
    ) -> None:
        # fk_references is "schema.table.column"
        parts = col.fk_references.split(".")
        if len(parts) != 3:
            return
        ref_schema, ref_table, ref_col = parts
        ref_asset_fq = f"{crawl.source_name}::{ref_schema}.{ref_table}"
        ref_col_fq = f"{ref_asset_fq}.{ref_col}"
        from_col_fq = f"{crawl.source_name}::{asset.fully_qualified}.{col.name}"

        await self._neo4j.run_query(
            """
            MATCH (fc:DataColumn {fq_name: $from_col})
            MATCH (tc:DataColumn {fq_name: $to_col})
            MERGE (fc)-[:REFERENCES]->(tc)
            WITH fc, tc
            MATCH (fc)<-[:HAS_COLUMN]-(fa:DataAsset)
            MATCH (tc)<-[:HAS_COLUMN]-(ta:DataAsset)
            MERGE (fa)-[r:RELATED_TO]->(ta)
            SET r.via = $via
            """,
            {
                "from_col": from_col_fq,
                "to_col": ref_col_fq,
                "via": f"{col.name} -> {col.fk_references}",
            },
            trace_id=trace_id,
        )

    async def _write_proposal(
        self,
        crawl: CrawlResult,
        proposal: AssetProposal,
        run_id: str,
        crawler_id: str,
        trace_id: str = "",
    ) -> None:
        # Merge domain and entity
        await self._neo4j.run_query(
            """
            MERGE (d:BusinessDomain {name: $domain})
            MERGE (e:BusinessEntity {name: $entity, domain: $domain})
            MERGE (d)-[:HAS_ENTITY]->(e)
            """,
            {"domain": proposal.domain, "entity": proposal.entity},
            trace_id=trace_id,
        )

        asset_fq = f"{crawl.source_name}::{proposal.asset.fully_qualified}"

        # Per-column attribute + MAPS_TO edge + audit row
        audit_rows: List[tuple] = []
        for m in proposal.columns:
            col_fq = f"{asset_fq}.{m.column_name}"
            attr_fq = f"{proposal.domain}.{proposal.entity}.{m.attribute}"
            await self._neo4j.run_query(
                """
                MATCH (e:BusinessEntity {name: $entity, domain: $domain})
                MATCH (c:DataColumn {fq_name: $col_fq})
                MERGE (ba:BusinessAttribute {fq_name: $attr_fq})
                SET ba.name   = $attr_name,
                    ba.entity = $entity,
                    ba.domain = $domain
                MERGE (e)-[:HAS_ATTRIBUTE]->(ba)
                MERGE (ba)-[m:MAPS_TO]->(c)
                SET m.confidence    = $confidence,
                    m.status        = 'AUTO_ACCEPTED',
                    m.model_version = $model_version,
                    m.reasoning     = $reasoning,
                    m.updated_at    = datetime()
                """,
                {
                    "entity": proposal.entity,
                    "domain": proposal.domain,
                    "col_fq": col_fq,
                    "attr_fq": attr_fq,
                    "attr_name": m.attribute,
                    "confidence": float(m.confidence),
                    "model_version": proposal.model_version,
                    "reasoning": m.reasoning[:500],
                },
                trace_id=trace_id,
            )

            # Find the CrawledColumn to get data_type + sample values
            crawled_col = next(
                (c for c in proposal.asset.columns if c.name == m.column_name),
                None,
            )
            audit_rows.append((
                str(uuid.uuid4()),
                run_id,
                crawler_id,
                crawl.source_uri,
                proposal.asset.fully_qualified,
                m.column_name,
                (crawled_col.data_type if crawled_col else ""),
                bool(crawled_col.is_pk) if crawled_col else False,
                bool(crawled_col.is_fk) if crawled_col else False,
                json.dumps([str(v)[:120] for v in (crawled_col.sample_values or [])]) if crawled_col else "[]",
                proposal.domain,
                proposal.entity,
                m.attribute,
                float(m.confidence),
                m.reasoning[:1000],
                proposal.model_version,
            ))

        if audit_rows:
            conn = self._mysql()
            try:
                cur = conn.cursor()
                cur.executemany(
                    """
                    INSERT INTO semantic_mapping_decisions
                        (decision_id, run_id, crawler_id,
                         data_source, data_asset, data_column, data_type,
                         is_pk, is_fk, sample_values,
                         proposed_domain, proposed_entity, proposed_attribute,
                         confidence, reasoning, model_version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    audit_rows,
                )
                conn.commit()
            finally:
                conn.close()
