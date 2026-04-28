"""Crawler runner — the async entry point called by the HTTP route.

Steps:
  1. Look up the crawler config row from pmos.crawlers
  2. Insert a RUNNING row into pmos.crawl_runs
  3. Instantiate the right crawler class for the source_type
  4. Run discover() (sync, in a thread)
  5. Loop over assets and call SemanticMapper.map_asset() per table
  6. Hand the crawl result + proposals to CatalogWriter
  7. Update the crawl_runs row with final stats

Invoked as a FastAPI BackgroundTask so the HTTP handler returns immediately
with the run_id the caller can poll.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional

import mysql.connector

from app.adapters.llm_adapter import LLMAdapter
from app.adapters.neo4j_adapter import Neo4jAdapter
from app.config import settings
from app.services.crawler.base import BaseCrawler, CrawlResult
from app.services.crawler.catalog_writer import CatalogWriter
from app.services.crawler.mysql_crawler import MySQLCrawler
from app.services.crawler.neo4j_crawler import Neo4jCrawler
from app.services.crawler.semantic_mapper import AssetProposal, SemanticMapper
from app.services.crawler.synonym_consolidator import SynonymConsolidator

logger = logging.getLogger("pmos.crawler.runner")


CRAWLER_CLASSES: Dict[str, type] = {
    "MYSQL": MySQLCrawler,
    "NEO4J": Neo4jCrawler,
}


def _mysql_conn():
    return mysql.connector.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        connection_timeout=10,
    )


def _get_crawler_row(crawler_id: str) -> Optional[Dict[str, Any]]:
    conn = _mysql_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT crawler_id, name, source_type, connection, options FROM crawlers WHERE crawler_id=%s",
            (crawler_id,),
        )
        row = cur.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    # Parse JSON columns
    for jf in ("connection", "options"):
        v = row.get(jf)
        if isinstance(v, str):
            try:
                row[jf] = json.loads(v)
            except Exception:
                row[jf] = {}
    return row


def _insert_run(run_id: str, crawler_id: str, trace_id: str, triggered_by: str) -> None:
    conn = _mysql_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO crawl_runs (run_id, crawler_id, status, trace_id, triggered_by)
            VALUES (%s, %s, 'RUNNING', %s, %s)
            """,
            (run_id, crawler_id, trace_id, triggered_by),
        )
        conn.commit()
    finally:
        conn.close()


def _finalize_run(
    run_id: str,
    status: str,
    assets: int,
    columns: int,
    mappings: int,
    entities: int,
    duration_ms: int,
    error: Optional[str],
    stats_json: Optional[Dict[str, Any]] = None,
) -> None:
    conn = _mysql_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE crawl_runs
               SET finished_at = NOW(),
                   status = %s,
                   assets_found = %s,
                   columns_found = %s,
                   mappings_made = %s,
                   entities_created = %s,
                   duration_ms = %s,
                   error_message = %s,
                   stats = %s
             WHERE run_id = %s
            """,
            (
                status, assets, columns, mappings, entities,
                duration_ms, error, json.dumps(stats_json or {}), run_id,
            ),
        )
        cur.execute(
            """
            UPDATE crawlers
               SET last_run_at = NOW(),
                   last_run_status = %s
             WHERE crawler_id = %s
            """,
            (status, _get_crawler_id_for_run(run_id) or ""),
        )
        conn.commit()
    finally:
        conn.close()


def _get_crawler_id_for_run(run_id: str) -> Optional[str]:
    conn = _mysql_conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT crawler_id FROM crawl_runs WHERE run_id=%s", (run_id,))
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        conn.close()


async def run_crawler_async(
    crawler_id: str,
    neo4j: Neo4jAdapter,
    llm: Optional[LLMAdapter] = None,
    trace_id: str = "",
    triggered_by: str = "api",
) -> Dict[str, Any]:
    """Execute one crawl end-to-end. Safe to call as a FastAPI BackgroundTask.

    Returns a summary dict (same shape as the crawl_runs row after update).
    """
    t0 = time.monotonic()
    run_id = str(uuid.uuid4())
    trace_id = trace_id or str(uuid.uuid4())

    row = _get_crawler_row(crawler_id)
    if not row:
        logger.warning("crawler %s not found", crawler_id)
        return {"run_id": run_id, "status": "FAILURE", "error": "crawler not found"}

    source_type = row["source_type"].upper()
    cls = CRAWLER_CLASSES.get(source_type)
    if cls is None:
        logger.warning("no crawler class registered for source_type=%s", source_type)
        _insert_run(run_id, crawler_id, trace_id, triggered_by)
        _finalize_run(
            run_id, "FAILURE", 0, 0, 0, 0,
            int((time.monotonic() - t0) * 1000),
            f"no crawler class for {source_type}",
        )
        return {"run_id": run_id, "status": "FAILURE", "error": f"no crawler class for {source_type}"}

    _insert_run(run_id, crawler_id, trace_id, triggered_by)
    logger.info(
        "Crawl run started",
        extra={"run_id": run_id, "crawler_id": crawler_id, "source_type": source_type},
    )

    error_message: Optional[str] = None
    status = "SUCCESS"
    crawl: Optional[CrawlResult] = None
    proposals: list[AssetProposal] = []
    asset_stats: Dict[str, Any] = {}

    try:
        # 1. Run the (sync) discovery step in a thread so we don't block the loop.
        crawler = cls({"connection": row.get("connection", {}), "options": row.get("options", {})})
        crawl = await asyncio.to_thread(crawler.discover)

        if crawl.errors:
            error_message = "; ".join(crawl.errors[:5])
            status = "PARTIAL" if crawl.assets else "FAILURE"

        # 2. Semantic mapping per asset
        mapper = SemanticMapper(llm=llm)
        for asset in crawl.assets:
            try:
                proposal = await mapper.map_asset(asset, trace_id=trace_id)
            except Exception as exc:
                logger.warning("mapping failed for %s: %s", asset.fully_qualified, exc)
                # map_asset itself catches errors, this is belt-and-braces
                continue
            proposals.append(proposal)
            asset_stats[asset.fully_qualified] = {
                "columns": len(asset.columns),
                "mapped": len(proposal.columns),
                "entity": proposal.entity,
                "domain": proposal.domain,
            }

        # 3. Write to Neo4j + MySQL audit
        writer = CatalogWriter(neo4j=neo4j)
        write_stats = await writer.write(
            crawl=crawl,
            proposals=proposals,
            run_id=run_id,
            crawler_id=crawler_id,
            trace_id=trace_id,
        )

        # 4. Phase F5 — post-crawl synonym consolidation pass.
        # Cluster all BusinessAttribute names produced (per-domain) so a
        # Data Steward can pick canonical names + canonical columns. Failure
        # here MUST NOT fail the crawl — it's an offline-style pass.
        if proposals:
            # Determine the dominant domain from the proposals (most-frequent),
            # so we cluster only BAs the crawl just touched. If the crawl
            # spanned multiple domains we pass None and let the consolidator
            # walk every domain.
            domain_counts: Dict[str, int] = {}
            for p in proposals:
                d = (p.domain or "").strip()
                if d:
                    domain_counts[d] = domain_counts.get(d, 0) + 1
            detected_domain: Optional[str] = None
            if len(domain_counts) == 1:
                detected_domain = next(iter(domain_counts.keys()))

            try:
                consolidator = SynonymConsolidator()
                await consolidator.run(
                    neo4j=neo4j,
                    llm=llm,
                    domain=detected_domain,
                    trace_id=trace_id,
                )
            except Exception as exc:
                logger.warning(
                    "SynonymConsolidator failed (non-fatal): %s",
                    exc,
                    extra={"run_id": run_id, "trace_id": trace_id},
                )

        duration_ms = int((time.monotonic() - t0) * 1000)
        _finalize_run(
            run_id=run_id,
            status=status,
            assets=write_stats.assets,
            columns=write_stats.columns,
            mappings=write_stats.mappings,
            entities=write_stats.entities,
            duration_ms=duration_ms,
            error=error_message,
            stats_json={"assets": asset_stats, "domains": write_stats.domains},
        )
        logger.info(
            "Crawl run finished",
            extra={
                "run_id": run_id, "status": status,
                "assets": write_stats.assets, "columns": write_stats.columns,
                "mappings": write_stats.mappings, "duration_ms": duration_ms,
            },
        )
        return {
            "run_id": run_id,
            "status": status,
            "assets": write_stats.assets,
            "columns": write_stats.columns,
            "mappings": write_stats.mappings,
            "entities": write_stats.entities,
            "duration_ms": duration_ms,
            "error": error_message,
        }

    except Exception as exc:
        logger.exception("Crawl run failed")
        duration_ms = int((time.monotonic() - t0) * 1000)
        _finalize_run(
            run_id=run_id, status="FAILURE",
            assets=0, columns=0, mappings=0, entities=0,
            duration_ms=duration_ms, error=str(exc),
        )
        return {"run_id": run_id, "status": "FAILURE", "error": str(exc)}
