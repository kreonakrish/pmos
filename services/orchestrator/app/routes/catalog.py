"""Data Catalog endpoints — crawler registry, runs, ontology, audit review.

All endpoints are read-only except:
  POST /v1/catalog/crawlers                              — create a crawler
  POST /v1/catalog/crawlers/{crawler_id}/run             — trigger a background crawl
  POST /v1/catalog/mapping-decisions/{decision_id}/review — auditor feedback

The `review` endpoint is the reinforcement-feedback surface: the auditor
confirms / corrects / rejects an LLM-proposed mapping and the system stores
the outcome with a reward signal for future training.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import mysql.connector
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import settings
from app.middleware.rbac import require_permission
from app.services.crawler import SynonymConsolidator, run_crawler_async
from app.utils.logger import logger

# Phase F5 — synonym merge audit. Prefer the shared writer (matches the
# translator side), fall back to the orchestrator-local writer when the
# ``shared`` package isn't deployed inside this image.
try:  # pragma: no cover - import guard
    from shared.audit import get_audit as _get_audit  # type: ignore
except Exception:  # pragma: no cover - import guard
    from app.utils.audit import audit as _local_audit

    class _LocalAuditAdapter:
        async def write(self, **kwargs):
            await _local_audit.write(**kwargs)

    def _get_audit(_settings):  # noqa: ANN001 - stub signature parity
        return _LocalAuditAdapter()

router = APIRouter(prefix="/v1/catalog", tags=["catalog"])


# ---------------------------------------------------------------------------
# MySQL helper (short-lived, same pattern as governance.py / ml_insights.py)
# ---------------------------------------------------------------------------
def _conn():
    return mysql.connector.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        connection_timeout=10,
    )


def _fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall() or []
    finally:
        conn.close()
    out: List[Dict[str, Any]] = []
    for r in rows:
        clean: Dict[str, Any] = {}
        for k, v in r.items():
            if v is None:
                clean[k] = None
            elif hasattr(v, "isoformat"):
                clean[k] = v.isoformat()
            elif isinstance(v, (bytes, bytearray)):
                try:
                    clean[k] = v.decode("utf-8")
                except Exception:
                    clean[k] = str(v)
            elif isinstance(v, str) and (v.startswith("{") or v.startswith("[")):
                try:
                    clean[k] = json.loads(v)
                except Exception:
                    clean[k] = v
            else:
                try:
                    json.dumps(v)
                    clean[k] = v
                except Exception:
                    clean[k] = str(v)
        out.append(clean)
    return out


def _get_neo4j(request: Request):
    return request.app.state.neo4j


def _get_llm(request: Request):
    try:
        return request.app.state.pipeline._llm
    except Exception:
        return None


def _serialize_neo4j(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _serialize_neo4j(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize_neo4j(v) for v in obj]
    return str(obj)


# ---------------------------------------------------------------------------
# Crawler registry
# ---------------------------------------------------------------------------
@router.get("/crawlers")
async def list_crawlers(request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    rows = _fetch(
        """
        SELECT crawler_id, name, description, source_type, connection, options,
               schedule_cron, status, last_run_at, last_run_status, created_at
        FROM crawlers
        ORDER BY created_at DESC
        """,
    )
    return {"trace_id": trace_id, "crawlers": rows, "count": len(rows)}


class CreateCrawlerRequest(BaseModel):
    name: str
    description: Optional[str] = ""
    source_type: str
    connection: Dict[str, Any]
    options: Optional[Dict[str, Any]] = None
    schedule_cron: Optional[str] = None


@router.post("/crawlers", dependencies=[Depends(require_permission("catalog.write"))])
async def create_crawler(
    request: Request,
    body: CreateCrawlerRequest,
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    crawler_id = str(uuid.uuid4())

    allowed = {"MYSQL", "POSTGRES", "SQLSERVER", "ORACLE", "TERADATA",
               "SNOWFLAKE", "GLUE", "S3", "EXCEL", "CSV", "SSRS_RDL",
               "NEO4J"}
    st = body.source_type.upper()
    if st not in allowed:
        raise HTTPException(
            status_code=400,
            detail={"error": f"unsupported source_type {st}", "trace_id": trace_id},
        )

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO crawlers
                (crawler_id, name, description, source_type, connection, options, schedule_cron, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,'ACTIVE')
            """,
            (
                crawler_id, body.name, body.description or "",
                st,
                json.dumps(body.connection),
                json.dumps(body.options or {}),
                body.schedule_cron,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {"trace_id": trace_id, "crawler_id": crawler_id, "status": "ACTIVE"}


@router.post(
    "/crawlers/{crawler_id}/run",
    dependencies=[Depends(require_permission("catalog.write"))],
)
async def run_crawler(
    crawler_id: str,
    request: Request,
    background: BackgroundTasks,
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    rows = _fetch("SELECT crawler_id, name, source_type FROM crawlers WHERE crawler_id=%s", (crawler_id,))
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={"error": "crawler not found", "crawler_id": crawler_id, "trace_id": trace_id},
        )

    neo4j = _get_neo4j(request)
    llm = _get_llm(request)

    background.add_task(
        run_crawler_async,
        crawler_id=crawler_id,
        neo4j=neo4j,
        llm=llm,
        trace_id=trace_id,
        triggered_by="api",
    )

    logger.info(
        "Crawl queued",
        layer="router",
        crawler_id=crawler_id,
        trace_id=trace_id,
    )
    return {"trace_id": trace_id, "crawler_id": crawler_id, "status": "QUEUED"}


@router.get("/crawlers/{crawler_id}/runs")
async def list_runs(
    crawler_id: str,
    request: Request,
    limit: int = Query(20, ge=1, le=200),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    rows = _fetch(
        f"""
        SELECT run_id, crawler_id, started_at, finished_at, status,
               assets_found, columns_found, mappings_made, entities_created,
               duration_ms, error_message, triggered_by
        FROM crawl_runs
        WHERE crawler_id = %s
        ORDER BY started_at DESC
        LIMIT {int(limit)}
        """,
        (crawler_id,),
    )
    return {"trace_id": trace_id, "runs": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# Assets (from Neo4j)
# ---------------------------------------------------------------------------
@router.get("/assets")
async def list_assets(
    request: Request,
    source_name: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)
    cypher = """
    MATCH (s:DataSource)-[:HAS_ASSET]->(a:DataAsset)
    WHERE $source_name = '' OR s.source_name = $source_name
    OPTIONAL MATCH (a)-[:HAS_COLUMN]->(c:DataColumn)
    WITH s, a, count(c) AS column_count
    RETURN s.source_name AS source_name, s.source_type AS source_type,
           a.fq_name AS fq_name, a.fully_qualified AS fully_qualified,
           a.asset_type AS asset_type, a.schema_name AS schema_name,
           a.asset_name AS asset_name, a.row_count AS row_count,
           a.comment AS comment, column_count
    ORDER BY fully_qualified
    LIMIT $limit
    """
    try:
        rows = await neo4j.run_query(
            cypher,
            {"source_name": source_name or "", "limit": int(limit)},
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("assets query failed", layer="router", error=str(exc), trace_id=trace_id)
        return {"trace_id": trace_id, "assets": [], "error": str(exc)}
    assets = [_serialize_neo4j(dict(r)) for r in (rows or [])]
    return {"trace_id": trace_id, "assets": assets, "count": len(assets)}


@router.get("/assets/{fq_name:path}")
async def get_asset(
    fq_name: str,
    request: Request,
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)
    try:
        asset_rows = await neo4j.run_query(
            """
            MATCH (a:DataAsset {fq_name: $fq_name})
            OPTIONAL MATCH (a)<-[:HAS_ASSET]-(s:DataSource)
            RETURN a, s.source_name AS source_name, s.source_type AS source_type
            LIMIT 1
            """,
            {"fq_name": fq_name},
            trace_id=trace_id,
        )
        if not asset_rows:
            raise HTTPException(
                status_code=404,
                detail={"error": "asset not found", "fq_name": fq_name, "trace_id": trace_id},
            )
        asset = _serialize_neo4j(dict(asset_rows[0]["a"]))
        asset["source_name"] = asset_rows[0].get("source_name")
        asset["source_type"] = asset_rows[0].get("source_type")

        col_rows = await neo4j.run_query(
            """
            MATCH (:DataAsset {fq_name: $fq_name})-[:HAS_COLUMN]->(c:DataColumn)
            OPTIONAL MATCH (ba:BusinessAttribute)-[m:MAPS_TO]->(c)
                WHERE m.effective_until IS NULL
            RETURN c, ba.name AS attribute, ba.domain AS domain, ba.entity AS entity,
                   m.confidence AS confidence, m.status AS mapping_status,
                   m.version AS version
            ORDER BY c.ordinal
            """,
            {"fq_name": fq_name},
            trace_id=trace_id,
        )
        columns = []
        for r in (col_rows or []):
            c = _serialize_neo4j(dict(r["c"]))
            c["attribute"] = r.get("attribute")
            c["domain"] = r.get("domain")
            c["entity"] = r.get("entity")
            c["confidence"] = r.get("confidence")
            c["mapping_status"] = r.get("mapping_status")
            c["version"] = r.get("version")
            columns.append(c)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("asset detail failed", layer="router", error=str(exc), trace_id=trace_id)
        return {"trace_id": trace_id, "asset": None, "columns": [], "error": str(exc)}

    return {"trace_id": trace_id, "asset": asset, "columns": columns}


# ---------------------------------------------------------------------------
# Business Ontology
# ---------------------------------------------------------------------------
@router.get("/ontology")
async def ontology(request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)
    try:
        domain_rows = await neo4j.run_query(
            """
            MATCH (d:BusinessDomain)
            OPTIONAL MATCH (d)-[:HAS_ENTITY]->(e:BusinessEntity)
            OPTIONAL MATCH (e)-[:HAS_ATTRIBUTE]->(ba:BusinessAttribute)
            // Collect mapped physical columns per attribute (live MAPS_TO only).
            OPTIONAL MATCH (ba)-[map:MAPS_TO]->(col:DataColumn)
              WHERE map.effective_until IS NULL
            OPTIONAL MATCH (a:DataAsset)-[:HAS_COLUMN]->(col)
            OPTIONAL MATCH (ds:DataSource)-[:HAS_ASSET]->(a)
            WITH d, e, ba,
                 collect(DISTINCT {
                   column_fq_name: col.fq_name,
                   column_name: col.name,
                   asset_fq_name: a.fq_name,
                   source_name: ds.source_name,
                   source_uri: ds.source_uri,
                   confidence: map.confidence,
                   status: map.status,
                   is_canonical: coalesce(map.is_canonical, false)
                 }) AS mapped_columns
            WITH d, e,
                 collect(DISTINCT CASE WHEN ba IS NULL THEN null ELSE {
                   name: ba.name,
                   fq_name: ba.fq_name,
                   mapped_columns: [m IN mapped_columns WHERE m.column_fq_name IS NOT NULL]
                 } END) AS attribute_list_raw
            WITH d, e,
                 [a IN attribute_list_raw WHERE a IS NOT NULL] AS attribute_list
            RETURN d.name AS domain,
                   collect(DISTINCT CASE WHEN e IS NULL THEN null ELSE {
                     entity: e.name,
                     attributes: size(attribute_list),
                     attribute_list: attribute_list
                   } END) AS entities_raw
            """,
            {},
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("ontology query failed", layer="router", error=str(exc), trace_id=trace_id)
        return {"trace_id": trace_id, "domains": [], "error": str(exc)}

    domains = []
    for r in (domain_rows or []):
        entities_raw = r.get("entities_raw") or r.get("entities") or []
        entities = [e for e in entities_raw if e and e.get("entity")]
        domains.append({
            "domain": r.get("domain"),
            "entities": entities,
        })
    return {"trace_id": trace_id, "domains": domains}


# ---------------------------------------------------------------------------
# Ext2 — Report nodes (deterministic short-circuit catalog entries)
# ---------------------------------------------------------------------------
@router.get("/reports")
async def list_reports(
    request: Request,
    owner_team: Optional[str] = Query(None),
    system: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    """List Report nodes with their datasets and used business attributes.

    Backs the Data Catalog → Reports tab. Read-only; the underlying graph is
    populated by the report ingestion pipeline (Ext2 seed + crawlers).
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    clauses: List[str] = []
    params: Dict[str, Any] = {"limit": int(limit)}
    if owner_team:
        clauses.append("r.owner_team = $owner_team")
        params["owner_team"] = owner_team
    if system:
        clauses.append("r.system = $system")
        params["system"] = system.upper()
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    cypher = f"""
    MATCH (r:Report)
    {where}
    OPTIONAL MATCH (r)-[:HAS_DATASET]->(rd:ReportDataset)
    OPTIONAL MATCH (rd)-[:RUNS_ON]->(ds:DataSource)
    OPTIONAL MATCH (r)-[:USES_ATTRIBUTE]->(ba:BusinessAttribute)
    RETURN r.report_id   AS report_id,
           r.name        AS name,
           r.description AS description,
           r.system      AS system,
           r.owner_team  AS owner_team,
           r.created_at  AS created_at,
           r.updated_at  AS updated_at,
           collect(DISTINCT {{
             dataset_id:   rd.dataset_id,
             name:         rd.name,
             command:      rd.command,
             command_type: rd.command_type,
             source_uri:   ds.source_uri,
             source_name:  ds.source_name
           }}) AS datasets,
           collect(DISTINCT ba.fq_name) AS uses_attributes
    ORDER BY r.name
    LIMIT $limit
    """
    try:
        rows = await neo4j.run_query(cypher, params, trace_id=trace_id)
    except Exception as exc:
        logger.error(
            "reports query failed", layer="router",
            error=str(exc), trace_id=trace_id,
        )
        return {"trace_id": trace_id, "reports": [], "count": 0, "error": str(exc)}

    reports: List[Dict[str, Any]] = []
    for r in (rows or []):
        raw = _serialize_neo4j(dict(r))
        # Drop the placeholder dict that collect() emits when there are no
        # HAS_DATASET edges (every field is None).
        datasets = [
            d for d in (raw.get("datasets") or [])
            if d and d.get("dataset_id")
        ]
        uses = [a for a in (raw.get("uses_attributes") or []) if a]
        reports.append({
            "report_id":       raw.get("report_id"),
            "name":            raw.get("name"),
            "description":     raw.get("description") or "",
            "system":          raw.get("system"),
            "owner_team":      raw.get("owner_team"),
            "created_at":      raw.get("created_at"),
            "updated_at":      raw.get("updated_at"),
            "datasets":        datasets,
            "uses_attributes": uses,
        })

    return {"trace_id": trace_id, "reports": reports, "count": len(reports)}


# ---------------------------------------------------------------------------
# Mapping decisions — auditor review queue
# ---------------------------------------------------------------------------
@router.get("/mapping-decisions")
async def list_mapping_decisions(
    request: Request,
    status: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    clauses: List[str] = []
    params_list: List[Any] = []
    if status:
        clauses.append("status = %s")
        params_list.append(status.upper())
    if run_id:
        clauses.append("run_id = %s")
        params_list.append(run_id)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = _fetch(
        f"""
        SELECT decision_id, run_id, crawler_id, data_source, data_asset,
               data_column, data_type, is_pk, is_fk, sample_values,
               proposed_domain, proposed_entity, proposed_attribute,
               confidence, reasoning, model_version,
               status, auditor_domain, auditor_entity, auditor_attribute,
               auditor_note, reviewed_by, reviewed_at, reward_signal,
               created_at
        FROM semantic_mapping_decisions
        {where}
        ORDER BY
            (status='AUTO_ACCEPTED') DESC,
            confidence ASC,
            created_at DESC
        LIMIT {int(limit)}
        """,
        tuple(params_list),
    )
    return {"trace_id": trace_id, "decisions": rows, "count": len(rows)}


@router.get("/mapping-decisions/summary")
async def mapping_decisions_summary(request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    rows = _fetch(
        """
        SELECT
          COUNT(*) AS total,
          SUM(status='AUTO_ACCEPTED') AS auto_accepted,
          SUM(status='CONFIRMED')     AS confirmed,
          SUM(status='CORRECTED')     AS corrected,
          SUM(status='REJECTED')      AS rejected,
          AVG(confidence)             AS avg_confidence,
          SUM(CASE WHEN confidence < 0.5 THEN 1 ELSE 0 END) AS low_confidence
        FROM semantic_mapping_decisions
        """,
    )
    stats = rows[0] if rows else {}
    total = int(stats.get("total") or 0)
    reviewed = int(stats.get("confirmed") or 0) + int(stats.get("corrected") or 0) + int(stats.get("rejected") or 0)
    coverage = float(reviewed) / total if total else 0.0
    return {
        "trace_id": trace_id,
        "total": total,
        "auto_accepted": int(stats.get("auto_accepted") or 0),
        "confirmed": int(stats.get("confirmed") or 0),
        "corrected": int(stats.get("corrected") or 0),
        "rejected": int(stats.get("rejected") or 0),
        "avg_confidence": float(stats.get("avg_confidence") or 0.0),
        "low_confidence": int(stats.get("low_confidence") or 0),
        "review_coverage": coverage,
    }


class MappingReviewRequest(BaseModel):
    action: str                         # 'CONFIRM' | 'CORRECT' | 'REJECT'
    auditor_domain: Optional[str] = None
    auditor_entity: Optional[str] = None
    auditor_attribute: Optional[str] = None
    auditor_note: Optional[str] = None
    reviewed_by: Optional[str] = "admin"


@router.post(
    "/mapping-decisions/{decision_id}/review",
    dependencies=[Depends(require_permission("catalog.write"))],
)
async def review_mapping_decision(
    decision_id: str,
    request: Request,
    body: MappingReviewRequest,
) -> Dict[str, Any]:
    """Record an auditor decision for RL feedback.

    reward_signal:
      CONFIRM → +1.0   (LLM was right)
      CORRECT → -0.5   (LLM was partially wrong — auditor replaced some fields)
      REJECT  → -1.0   (mapping was garbage)
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    action = (body.action or "").upper()
    if action not in ("CONFIRM", "CORRECT", "REJECT"):
        raise HTTPException(
            status_code=400,
            detail={"error": "action must be CONFIRM | CORRECT | REJECT", "trace_id": trace_id},
        )

    decisions = _fetch(
        "SELECT * FROM semantic_mapping_decisions WHERE decision_id=%s",
        (decision_id,),
    )
    if not decisions:
        raise HTTPException(
            status_code=404,
            detail={"error": "decision not found", "decision_id": decision_id, "trace_id": trace_id},
        )
    decision = decisions[0]

    status = {"CONFIRM": "CONFIRMED", "CORRECT": "CORRECTED", "REJECT": "REJECTED"}[action]
    reward = {"CONFIRMED": 1.0, "CORRECTED": -0.5, "REJECTED": -1.0}[status]

    auditor_domain = body.auditor_domain or decision.get("proposed_domain")
    auditor_entity = body.auditor_entity or decision.get("proposed_entity")
    auditor_attribute = body.auditor_attribute or decision.get("proposed_attribute")

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE semantic_mapping_decisions
               SET status = %s,
                   auditor_domain    = %s,
                   auditor_entity    = %s,
                   auditor_attribute = %s,
                   auditor_note      = %s,
                   reviewed_by       = %s,
                   reviewed_at       = NOW(),
                   reward_signal     = %s
             WHERE decision_id = %s
            """,
            (
                status, auditor_domain, auditor_entity, auditor_attribute,
                body.auditor_note or "", body.reviewed_by or "admin",
                reward, decision_id,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Phase E4 — versioned MAPS_TO. Auditor reviews always touch Neo4j so the
    # version timeline reflects every confirm/correct/reject, not just
    # corrections. The semantics per action:
    #   CONFIRM  — bump version of the existing edge, refresh effective_from.
    #   CORRECT  — supersede: SET effective_until on the OLD edge to a different
    #              attribute, then CREATE a NEW MAPS_TO with version = old+1.
    #   REJECT   — supersede only: SET effective_until on the OLD edge with
    #              status='REJECTED'. No new edge.
    neo4j = _get_neo4j(request)
    data_asset = decision.get("data_asset") or ""
    data_column = decision.get("data_column") or ""
    proposed_domain = decision.get("proposed_domain")
    proposed_entity = decision.get("proposed_entity")
    proposed_attribute = decision.get("proposed_attribute")

    same_attribute = (
        auditor_domain == proposed_domain
        and auditor_entity == proposed_entity
        and auditor_attribute == proposed_attribute
    )

    try:
        rows = await neo4j.run_query(
            """
            MATCH (a:DataAsset {fully_qualified: $fq})
            RETURN a.fq_name AS asset_fq LIMIT 1
            """,
            {"fq": data_asset},
            trace_id=trace_id,
        )
        asset_fq = rows[0]["asset_fq"] if rows else None
        if not asset_fq:
            raise RuntimeError(f"DataAsset not found in Neo4j for {data_asset}")

        col_fq = f"{asset_fq}.{data_column}"
        old_attr_fq = (
            f"{proposed_domain}.{proposed_entity}.{proposed_attribute}"
            if proposed_domain and proposed_entity and proposed_attribute
            else None
        )
        new_attr_fq = f"{auditor_domain}.{auditor_entity}.{auditor_attribute}"
        reviewed_by = body.reviewed_by or "admin"

        if status == "CONFIRMED" and same_attribute:
            # Bump version on the current edge in place.
            await neo4j.run_query(
                """
                MATCH (ba:BusinessAttribute {fq_name: $attr_fq})
                      -[m:MAPS_TO]->(c:DataColumn {fq_name: $col_fq})
                WHERE m.effective_until IS NULL
                SET m.status         = 'CONFIRMED',
                    m.reviewed_by    = $reviewed_by,
                    m.reviewed_at    = datetime(),
                    m.confidence     = 1.0,
                    m.version        = coalesce(m.version, 1) + 1,
                    m.effective_from = datetime()
                """,
                {
                    "attr_fq": new_attr_fq,
                    "col_fq": col_fq,
                    "reviewed_by": reviewed_by,
                },
                trace_id=trace_id,
            )

        elif status in ("CORRECTED",) or (status == "CONFIRMED" and not same_attribute):
            # Supersede: close OLD edge to proposed attr, create NEW edge to
            # auditor's chosen attr with version = old.version + 1. We do this
            # in two passes so we can read the old version before creating
            # the new edge.
            old_rows: List[Dict[str, Any]] = []
            if old_attr_fq:
                old_rows = await neo4j.run_query(
                    """
                    MATCH (ba:BusinessAttribute {fq_name: $old_attr_fq})
                          -[m:MAPS_TO]->(c:DataColumn {fq_name: $col_fq})
                    WHERE m.effective_until IS NULL
                    SET m.effective_until = datetime(),
                        m.status          = $supersede_status
                    RETURN coalesce(m.version, 1) AS old_version
                    """,
                    {
                        "old_attr_fq": old_attr_fq,
                        "col_fq": col_fq,
                        "supersede_status": "SUPERSEDED",
                    },
                    trace_id=trace_id,
                )
            old_version = int(old_rows[0]["old_version"]) if old_rows else 0
            new_version = old_version + 1

            await neo4j.run_query(
                """
                MERGE (d:BusinessDomain {name: $domain})
                MERGE (e:BusinessEntity {name: $entity, domain: $domain})
                MERGE (d)-[:HAS_ENTITY]->(e)
                MERGE (ba:BusinessAttribute {fq_name: $attr_fq})
                SET ba.name = $attr_name, ba.entity = $entity, ba.domain = $domain
                MERGE (e)-[:HAS_ATTRIBUTE]->(ba)
                WITH ba
                MATCH (c:DataColumn {fq_name: $col_fq})
                CREATE (ba)-[m:MAPS_TO {
                    confidence: 1.0,
                    status: $status,
                    reviewed_by: $reviewed_by,
                    reviewed_at: datetime(),
                    version: $new_version,
                    effective_from: datetime(),
                    effective_until: null
                }]->(c)
                """,
                {
                    "domain": auditor_domain,
                    "entity": auditor_entity,
                    "attr_fq": new_attr_fq,
                    "attr_name": auditor_attribute,
                    "col_fq": col_fq,
                    "status": status,
                    "reviewed_by": reviewed_by,
                    "new_version": new_version,
                },
                trace_id=trace_id,
            )

        elif status == "REJECTED":
            # Close the old edge only — no replacement.
            if old_attr_fq:
                await neo4j.run_query(
                    """
                    MATCH (ba:BusinessAttribute {fq_name: $old_attr_fq})
                          -[m:MAPS_TO]->(c:DataColumn {fq_name: $col_fq})
                    WHERE m.effective_until IS NULL
                    SET m.effective_until = datetime(),
                        m.status          = 'REJECTED',
                        m.reviewed_by     = $reviewed_by,
                        m.reviewed_at     = datetime()
                    """,
                    {
                        "old_attr_fq": old_attr_fq,
                        "col_fq": col_fq,
                        "reviewed_by": reviewed_by,
                    },
                    trace_id=trace_id,
                )
    except Exception as exc:
        logger.warning(
            "Neo4j review update failed (non-fatal)",
            layer="router", error=str(exc), decision_id=decision_id, trace_id=trace_id,
        )

    return {
        "trace_id": trace_id,
        "decision_id": decision_id,
        "status": status,
        "reward_signal": reward,
    }


# ---------------------------------------------------------------------------
# Phase E4 — Mapping version history (replay / "explain why")
# ---------------------------------------------------------------------------
@router.get("/mapping-history")
async def mapping_history(
    request: Request,
    attribute_fq_name: str = Query(..., description="BusinessAttribute.fq_name"),
) -> Dict[str, Any]:
    """Full version timeline for a BusinessAttribute mapping.

    Returns every MAPS_TO edge that ever pointed out of the given
    BusinessAttribute, current and superseded, ordered by version. Used by
    the Mapping Review tab's "History" affordance to explain why an answer
    was generated against a particular ontology binding.
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)
    cypher = """
    MATCH (ba:BusinessAttribute {fq_name: $attribute_fq_name})
          -[m:MAPS_TO]->(c:DataColumn)
    RETURN coalesce(m.version, 1)        AS version,
           m.status                      AS status,
           m.confidence                  AS confidence,
           m.reviewed_by                 AS reviewed_by,
           m.reviewed_at                 AS reviewed_at,
           m.effective_from              AS effective_from,
           m.effective_until             AS effective_until,
           c.fq_name                     AS column_fq_name
    ORDER BY version ASC, effective_from ASC
    """
    try:
        rows = await neo4j.run_query(
            cypher, {"attribute_fq_name": attribute_fq_name}, trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("mapping history query failed", layer="router",
                     error=str(exc), trace_id=trace_id)
        raise HTTPException(status_code=500, detail={"error": str(exc), "trace_id": trace_id})

    history = [_serialize_neo4j(dict(r)) for r in (rows or [])]
    return {
        "trace_id": trace_id,
        "attribute_fq_name": attribute_fq_name,
        "history": history,
        "count": len(history),
    }


# ---------------------------------------------------------------------------
# Phase A5 — feeders for new UI tabs
# ---------------------------------------------------------------------------


def _get_ontology_neo4j(request: Request):
    """Ontology graph (may be the same Neo4j as execution; falls back if unset)."""
    return getattr(request.app.state, "ontology_neo4j", None) or request.app.state.neo4j


@router.get("/lineage")
async def catalog_lineage(
    request: Request,
    domain: Optional[str] = Query(None, description="Filter by BusinessDomain.name"),
    asset: Optional[str] = Query(None, description="Filter by DataAsset.fq_name"),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    """Asset ↔ Ontology ↔ Source ↔ CrawlRun ↔ Tool lineage view.

    Powers the Data Catalog "Lineage & Runs" tab.
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    clauses: List[str] = []
    params: Dict[str, Any] = {"limit": int(limit)}
    if domain:
        clauses.append("d.name = $domain")
        params["domain"] = domain
    if asset:
        clauses.append("a.fq_name = $asset")
        params["asset"] = asset
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    cypher = f"""
    MATCH (a:DataAsset)
    OPTIONAL MATCH (ds:DataSource)-[:HAS_ASSET]->(a)
    OPTIONAL MATCH (a)-[:HAS_COLUMN]->(col:DataColumn)
    OPTIONAL MATCH (ba:BusinessAttribute)-[map:MAPS_TO]->(col)
    WHERE map.effective_until IS NULL
    OPTIONAL MATCH (e:BusinessEntity)-[:HAS_ATTRIBUTE]->(ba)
    OPTIONAL MATCH (d:BusinessDomain)-[:HAS_ENTITY]->(e)
    OPTIONAL MATCH (t:Tool)-[:ACCESSES]->(ds)
    {where}
    WITH a, ds, d, e, ba, map, t,
         collect(DISTINCT col.name) AS column_names
    RETURN
      a.fq_name             AS asset_fq_name,
      a.asset_type          AS asset_type,
      a.row_count           AS row_count,
      ds.source_name        AS source_name,
      ds.source_type        AS source_type,
      ds.source_uri         AS source_uri,
      collect(DISTINCT {{
        domain: d.name,
        entity: e.name,
        attribute: ba.name,
        confidence: map.confidence,
        status: map.status,
        version: map.version
      }}) AS ontology_links,
      collect(DISTINCT {{
        tool_id: t.tool_id,
        name: t.name,
        tool_type: t.tool_type
      }}) AS bound_tools,
      column_names
    ORDER BY asset_fq_name ASC
    LIMIT $limit
    """
    try:
        rows = await neo4j.run_query(cypher, params, trace_id=trace_id)
    except Exception as exc:
        logger.error("lineage query failed", layer="router",
                     error=str(exc), trace_id=trace_id)
        raise HTTPException(status_code=500, detail={"error": str(exc), "trace_id": trace_id})

    runs = _fetch(
        """
        SELECT cr.run_id, cr.crawler_id, c.name AS crawler_name,
               c.source_type, cr.status, cr.started_at, cr.finished_at,
               cr.assets_found AS assets_count, cr.columns_found AS columns_count,
               cr.error_message
        FROM crawl_runs cr
        JOIN crawlers c ON c.crawler_id = cr.crawler_id
        ORDER BY cr.started_at DESC
        LIMIT 50
        """,
    )

    cleaned: List[Dict[str, Any]] = []
    for r in rows:
        ontology = [
            o for o in (r.get("ontology_links") or [])
            if o and (o.get("entity") or o.get("attribute"))
        ]
        tools = [
            t for t in (r.get("bound_tools") or [])
            if t and t.get("tool_id")
        ]
        cleaned.append({
            "asset_fq_name": r.get("asset_fq_name"),
            "asset_type": r.get("asset_type"),
            "row_count": r.get("row_count"),
            "source_name": r.get("source_name"),
            "source_type": r.get("source_type"),
            "source_uri": r.get("source_uri"),
            "columns": [c for c in (r.get("column_names") or []) if c],
            "ontology_links": ontology,
            "bound_tools": tools,
        })

    return {
        "trace_id": trace_id,
        "assets": cleaned,
        "recent_runs": runs,
        "count": len(cleaned),
    }


@router.get("/tools/{tool_id}/coverage")
async def tool_coverage(
    tool_id: str,
    request: Request,
    sample_limit: int = Query(3, ge=0, le=10),
) -> Dict[str, Any]:
    """Per-tool coverage: physical assets reachable, business entities
    covered, and a few sample values per column.

    Powers the Tool Studio "Coverage" tab.
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)

    cypher = """
    MATCH (t:Tool {tool_id: $tool_id})
    OPTIONAL MATCH (t)-[:ACCESSES]->(ds:DataSource)
    OPTIONAL MATCH (ds)-[:HAS_ASSET]->(a:DataAsset)
    OPTIONAL MATCH (a)-[:HAS_COLUMN]->(col:DataColumn)
    OPTIONAL MATCH (ba:BusinessAttribute)-[map:MAPS_TO]->(col)
    WHERE map.effective_until IS NULL
    OPTIONAL MATCH (e:BusinessEntity)-[:HAS_ATTRIBUTE]->(ba)
    OPTIONAL MATCH (d:BusinessDomain)-[:HAS_ENTITY]->(e)
    WITH t, ds, a,
         collect(DISTINCT {
           name: col.name,
           data_type: col.data_type,
           sample_values: col.sample_values,
           business_attribute: ba.name,
           business_entity: e.name,
           business_domain: d.name,
           map_confidence: map.confidence
         }) AS columns
    RETURN
      t.tool_id     AS tool_id,
      t.name        AS tool_name,
      t.tool_type   AS tool_type,
      collect(DISTINCT {
        source_name: ds.source_name,
        source_uri: ds.source_uri,
        asset_fq_name: a.fq_name,
        asset_type: a.asset_type,
        row_count: a.row_count,
        columns: columns
      }) AS assets
    """
    try:
        rows = await neo4j.run_query(cypher, {"tool_id": tool_id}, trace_id=trace_id)
    except Exception as exc:
        logger.error("tool coverage query failed", layer="router",
                     error=str(exc), trace_id=trace_id, tool_id=tool_id)
        raise HTTPException(status_code=500, detail={"error": str(exc), "trace_id": trace_id})

    if not rows:
        raise HTTPException(
            status_code=404,
            detail={"error": "tool not found in Neo4j", "tool_id": tool_id, "trace_id": trace_id},
        )

    row = rows[0]
    assets_raw = [a for a in (row.get("assets") or []) if a and a.get("asset_fq_name")]
    assets: List[Dict[str, Any]] = []
    business_entities: set = set()
    for a in assets_raw:
        cols = [c for c in (a.get("columns") or []) if c and c.get("name")]
        for c in cols:
            sv = c.get("sample_values")
            if isinstance(sv, list) and sample_limit:
                c["sample_values"] = sv[:sample_limit]
            elif not sample_limit:
                c["sample_values"] = []
            if c.get("business_entity"):
                business_entities.add(c["business_entity"])
        assets.append({
            "source_name": a.get("source_name"),
            "source_uri": a.get("source_uri"),
            "asset_fq_name": a.get("asset_fq_name"),
            "asset_type": a.get("asset_type"),
            "row_count": a.get("row_count"),
            "columns": cols,
        })

    return {
        "trace_id": trace_id,
        "tool_id": row.get("tool_id"),
        "tool_name": row.get("tool_name"),
        "tool_type": row.get("tool_type"),
        "assets": assets,
        "business_entities_covered": sorted(business_entities),
    }


@router.get("/schema-graph")
async def catalog_schema_graph(request: Request) -> Dict[str, Any]:
    """Live Neo4j ontology schema as nodes + relationships for visualization.

    Backs the Schema Graph page under the Data Sources nav.
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    ontology_neo4j = _get_ontology_neo4j(request)

    try:
        viz = await ontology_neo4j.run_query("CALL db.schema.visualization()")
    except Exception as exc:
        logger.error("schema visualization failed", layer="router",
                     error=str(exc), trace_id=trace_id)
        raise HTTPException(status_code=500, detail={"error": str(exc), "trace_id": trace_id})

    nodes: List[Dict[str, Any]] = []
    edges: List[Dict[str, Any]] = []
    seen_node_ids: set = set()

    def _node_label(n: Any) -> Optional[str]:
        # Neo4j Node has .labels (frozenset) and .get('name'); fall back to dict.
        if hasattr(n, "labels"):
            try:
                lbls = list(n.labels)  # type: ignore[attr-defined]
                if lbls:
                    return str(lbls[0])
            except Exception:
                pass
        if hasattr(n, "get"):
            try:
                v = n.get("name")  # type: ignore[union-attr]
                if v:
                    return str(v)
            except Exception:
                pass
        if isinstance(n, dict):
            return n.get("name") or n.get("label")
        return None

    def _node_props(n: Any) -> List[Any]:
        # Try dict-coercion; Node objects expose properties via items().
        try:
            if hasattr(n, "items"):
                d = dict(n.items())  # type: ignore[arg-type]
                return d.get("indexes") or d.get("properties") or []
        except Exception:
            pass
        if isinstance(n, dict):
            return n.get("indexes") or n.get("properties") or []
        return []

    for row in (viz or []):
        for n in (row.get("nodes") or []):
            label = _node_label(n)
            node_id = label or str(getattr(n, "element_id", "") or "")
            if not node_id or node_id in seen_node_ids:
                continue
            seen_node_ids.add(node_id)
            nodes.append({
                "id": node_id,
                "label": label,
                "properties": _node_props(n),
            })

        for r in (row.get("relationships") or []):
            # The driver's ``result.data()`` flattens a Relationship to the
            # 3-tuple ``[start_node_dict, "TYPE", end_node_dict]``. Handle both
            # that and the legacy dict-shape (``{type|name, startNode, endNode}``)
            # in case the Cypher procedure ever returns the latter.
            rel_type: Optional[str] = None
            start_node: Any = None
            end_node: Any = None

            if isinstance(r, (list, tuple)) and len(r) == 3:
                start_node, rel_type, end_node = r
            elif isinstance(r, dict):
                rel_type = r.get("name") or r.get("type")
                start_node = r.get("startNode") or r.get("start_node")
                end_node = r.get("endNode") or r.get("end_node")
            else:
                rel_type = getattr(r, "type", None)
                start_node = getattr(r, "start_node", None)
                end_node = getattr(r, "end_node", None)

            edges.append({
                "type": str(rel_type) if rel_type else None,
                "from": _node_label(start_node) if start_node is not None else None,
                "to": _node_label(end_node) if end_node is not None else None,
                "properties": [],
            })

    if not nodes:
        labels = await ontology_neo4j.run_query("CALL db.labels() YIELD label RETURN label")
        for row in labels or []:
            label = row.get("label")
            nodes.append({"id": label, "label": label, "properties": []})
        rel_types = await ontology_neo4j.run_query(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
        )
        for row in rel_types or []:
            edges.append({
                "type": row.get("relationshipType"),
                "from": None,
                "to": None,
                "properties": [],
            })

    return {"trace_id": trace_id, "nodes": nodes, "edges": edges,
            "node_count": len(nodes), "edge_count": len(edges)}


# ---------------------------------------------------------------------------
# Phase F5 — Synonym proposals (post-crawl LLM-clustered BAs)
# ---------------------------------------------------------------------------
class SynonymReviewRequest(BaseModel):
    action: str                               # 'CONFIRM' | 'REJECT'
    chosen_canonical_attr: Optional[str] = None
    chosen_canonical_column: Optional[str] = None
    reviewed_by: Optional[str] = "admin"
    note: Optional[str] = None


@router.get(
    "/synonym-proposals",
    dependencies=[Depends(require_permission("catalog.read"))],
)
async def list_synonym_proposals(
    request: Request,
    status: Optional[str] = Query(None, description="PROPOSED | IN_REVIEW | CONFIRMED | REJECTED | APPLIED | SUPERSEDED"),
    kind: Optional[str] = Query(None, description="SYNONYM | DUPLICATION | GRAIN | NAMING | OTHER"),
    domain: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    clauses: List[str] = []
    params_list: List[Any] = []
    if status:
        clauses.append("status = %s")
        params_list.append(status.upper())
    if kind:
        clauses.append("kind = %s")
        params_list.append(kind.upper())
    if domain:
        clauses.append("domain = %s")
        params_list.append(domain)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = _fetch(
        f"""
        SELECT proposal_id, kind, domain, members_json, member_columns_json,
               suggested_canonical_attr, suggested_canonical_column,
               rationale, confidence, status,
               chosen_canonical_attr, chosen_canonical_column,
               reviewed_by, reviewed_at, applied_at, created_at
        FROM synonym_proposals
        {where}
        ORDER BY (status='PROPOSED') DESC,
                 (status='IN_REVIEW') DESC,
                 created_at DESC
        LIMIT {int(limit)}
        """,
        tuple(params_list),
    )
    return {"trace_id": trace_id, "proposals": rows, "count": len(rows)}


@router.get(
    "/synonym-proposals/{proposal_id}",
    dependencies=[Depends(require_permission("catalog.read"))],
)
async def get_synonym_proposal(
    proposal_id: str,
    request: Request,
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    rows = _fetch(
        """
        SELECT proposal_id, kind, domain, members_json, member_columns_json,
               suggested_canonical_attr, suggested_canonical_column,
               rationale, confidence, status,
               chosen_canonical_attr, chosen_canonical_column,
               reviewed_by, reviewed_at, applied_at, created_at
        FROM synonym_proposals
        WHERE proposal_id = %s
        """,
        (proposal_id,),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={"error": "proposal not found", "proposal_id": proposal_id, "trace_id": trace_id},
        )
    return {"trace_id": trace_id, "proposal": rows[0]}


@router.post(
    "/synonym-proposals/{proposal_id}/review",
    dependencies=[Depends(require_permission("catalog.write"))],
)
async def review_synonym_proposal(
    proposal_id: str,
    request: Request,
    body: SynonymReviewRequest,
) -> Dict[str, Any]:
    """Auditor / Data Steward review of a synonym proposal.

    On CONFIRM with both ``chosen_canonical_attr`` and ``chosen_canonical_column``:
      1. Validate chosen_canonical_attr is in the cluster.
      2. Validate chosen_canonical_column is a DataColumn reachable from at
         least one cluster member.
      3. SUPERSEDE every live MAPS_TO out of the non-canonical BAs (set
         ``effective_until=datetime(), status='SUPERSEDED_BY_MERGE'``).
      4. MERGE secondary MAPS_TO from the canonical BA to each non-canonical
         physical column with ``status='SECONDARY', is_canonical=false`` so
         backwards-compat lookups still resolve.
      5. CREATE a new MAPS_TO from the canonical BA to the chosen canonical
         column with ``status='CANONICAL', is_canonical=true,
         version=max(version)+1, effective_from=datetime()``.
      6. DETACH DELETE non-canonical BAs that have no remaining HAS_ATTRIBUTE
         referrers, UNLESS a TaskNode still references their fq_name in
         ``canonical_entities``.
      7. Mark proposal ``status='APPLIED', applied_at=now``.
      8. Audit-log + auto-resolve matching OPEN ``SYNONYM_AMBIGUITY`` issues.
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    action = (body.action or "").upper()
    if action not in ("CONFIRM", "REJECT"):
        raise HTTPException(
            status_code=400,
            detail={"error": "action must be CONFIRM | REJECT", "trace_id": trace_id},
        )

    rows = _fetch(
        """
        SELECT proposal_id, kind, domain, members_json, member_columns_json,
               suggested_canonical_attr, suggested_canonical_column,
               status
        FROM synonym_proposals
        WHERE proposal_id = %s
        """,
        (proposal_id,),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={"error": "proposal not found", "proposal_id": proposal_id, "trace_id": trace_id},
        )
    proposal = rows[0]
    if proposal.get("status") in ("APPLIED", "SUPERSEDED"):
        raise HTTPException(
            status_code=409,
            detail={"error": f"proposal already {proposal.get('status')}", "trace_id": trace_id},
        )

    members = proposal.get("members_json") or []
    if isinstance(members, str):
        try:
            members = json.loads(members)
        except Exception:
            members = []
    if not isinstance(members, list):
        members = []

    reviewed_by = body.reviewed_by or "admin"

    # ---------------- REJECT path ----------------
    if action == "REJECT":
        conn = _conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE synonym_proposals
                   SET status = 'REJECTED',
                       reviewed_by = %s,
                       reviewed_at = NOW(3)
                 WHERE proposal_id = %s
                """,
                (reviewed_by, proposal_id),
            )
            conn.commit()
        finally:
            conn.close()
        try:
            await _get_audit(settings).write(
                trace_id=trace_id,
                actor=reviewed_by,
                actor_type="USER",
                action="catalog.synonym_merge_rejected",
                resource_type="synonym_proposals",
                resource_id=proposal_id,
                payload={"members": members, "note": body.note},
            )
        except Exception:
            pass
        return {"trace_id": trace_id, "proposal_id": proposal_id, "status": "REJECTED"}

    # ---------------- CONFIRM path ----------------
    chosen_attr = (body.chosen_canonical_attr or proposal.get("suggested_canonical_attr") or "").strip()
    chosen_col = (body.chosen_canonical_column or proposal.get("suggested_canonical_column") or "").strip()
    if not chosen_attr or not chosen_col:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "chosen_canonical_attr and chosen_canonical_column are required for CONFIRM",
                "trace_id": trace_id,
            },
        )
    if chosen_attr not in members:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "chosen_canonical_attr is not a member of the cluster",
                "members": members,
                "trace_id": trace_id,
            },
        )

    neo4j = _get_neo4j(request)

    # Verify chosen_canonical_column is reachable from at least one cluster member.
    try:
        col_check = await neo4j.run_query(
            """
            MATCH (ba:BusinessAttribute)-[:MAPS_TO]->(c:DataColumn {fq_name: $col_fq})
            WHERE ba.fq_name IN $members
            RETURN count(c) AS hits
            """,
            {"col_fq": chosen_col, "members": members},
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error(
            "synonym proposal Neo4j column check failed",
            layer="router", error=str(exc), trace_id=trace_id,
        )
        raise HTTPException(status_code=500, detail={"error": str(exc), "trace_id": trace_id})
    hits = int((col_check or [{}])[0].get("hits") or 0)
    if hits == 0:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "chosen_canonical_column is not reachable from any cluster member",
                "trace_id": trace_id,
            },
        )

    non_canonical = [m for m in members if m != chosen_attr]

    # 1. Supersede every live MAPS_TO out of the non-canonical BAs.
    try:
        await neo4j.run_query(
            """
            UNWIND $non_canonical AS old_attr_fq
            MATCH (ba:BusinessAttribute {fq_name: old_attr_fq})
                  -[m:MAPS_TO]->(c:DataColumn)
            WHERE m.effective_until IS NULL
            SET m.effective_until = datetime(),
                m.status          = 'SUPERSEDED_BY_MERGE',
                m.superseded_by   = $canonical_attr_fq,
                m.reviewed_by     = $reviewed_by,
                m.reviewed_at     = datetime()
            """,
            {
                "non_canonical": non_canonical,
                "canonical_attr_fq": chosen_attr,
                "reviewed_by": reviewed_by,
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("synonym supersede failed", layer="router",
                     error=str(exc), trace_id=trace_id)
        raise HTTPException(status_code=500, detail={"error": str(exc), "trace_id": trace_id})

    # 2. MERGE secondary MAPS_TO from canonical BA to every non-canonical column,
    # so the canonical BA "absorbs" all reachable physical columns. is_canonical=false
    # so the translator prefers the CANONICAL edge.
    try:
        await neo4j.run_query(
            """
            MATCH (canonical:BusinessAttribute {fq_name: $canonical_attr_fq})
            UNWIND $non_canonical AS old_attr_fq
            MATCH (old:BusinessAttribute {fq_name: old_attr_fq})
                  -[old_edge:MAPS_TO]->(c:DataColumn)
            WHERE old_edge.effective_until = datetime()
               OR old_edge.status = 'SUPERSEDED_BY_MERGE'
            WITH canonical, c
            WHERE canonical.fq_name <> ''
            MERGE (canonical)-[m:MAPS_TO {effective_until: null, status: 'SECONDARY'}]->(c)
              ON CREATE SET m.is_canonical    = false,
                            m.confidence      = 0.5,
                            m.effective_from  = datetime(),
                            m.merged_from     = $non_canonical,
                            m.reviewed_by     = $reviewed_by,
                            m.reviewed_at     = datetime(),
                            m.version         = 1
            """,
            {
                "canonical_attr_fq": chosen_attr,
                "non_canonical": non_canonical,
                "reviewed_by": reviewed_by,
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning(
            "synonym secondary MAPS_TO merge failed (non-fatal)",
            layer="router", error=str(exc), trace_id=trace_id,
        )

    # 3. Create the new CANONICAL MAPS_TO edge to the chosen physical column.
    try:
        version_rows = await neo4j.run_query(
            """
            MATCH (ba:BusinessAttribute {fq_name: $canonical_attr_fq})
                  -[m:MAPS_TO]->(:DataColumn)
            RETURN coalesce(max(m.version), 0) AS max_version
            """,
            {"canonical_attr_fq": chosen_attr},
            trace_id=trace_id,
        )
        max_version = int((version_rows or [{}])[0].get("max_version") or 0)
        new_version = max_version + 1

        await neo4j.run_query(
            """
            MATCH (ba:BusinessAttribute {fq_name: $canonical_attr_fq})
            MATCH (c:DataColumn {fq_name: $col_fq})
            // Close any prior live edge to a *different* column so we have one live CANONICAL.
            WITH ba, c
            OPTIONAL MATCH (ba)-[prior:MAPS_TO]->(other:DataColumn)
              WHERE prior.effective_until IS NULL AND other.fq_name <> $col_fq
            FOREACH (e IN CASE WHEN prior IS NULL THEN [] ELSE [prior] END |
              SET e.effective_until = datetime(),
                  e.status          = 'SUPERSEDED_BY_MERGE',
                  e.superseded_by   = $canonical_attr_fq
            )
            WITH ba, c
            MERGE (ba)-[m:MAPS_TO {effective_until: null, status: 'CANONICAL'}]->(c)
              ON CREATE SET m.is_canonical   = true,
                            m.confidence     = 1.0,
                            m.effective_from = datetime(),
                            m.reviewed_by    = $reviewed_by,
                            m.reviewed_at    = datetime(),
                            m.version        = $new_version
              ON MATCH  SET m.is_canonical   = true,
                            m.confidence     = 1.0,
                            m.reviewed_by    = $reviewed_by,
                            m.reviewed_at    = datetime(),
                            m.version        = $new_version,
                            m.effective_from = datetime()
            """,
            {
                "canonical_attr_fq": chosen_attr,
                "col_fq": chosen_col,
                "reviewed_by": reviewed_by,
                "new_version": new_version,
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("synonym canonical MAPS_TO create failed", layer="router",
                     error=str(exc), trace_id=trace_id)
        raise HTTPException(status_code=500, detail={"error": str(exc), "trace_id": trace_id})

    # 4. DETACH DELETE non-canonical BAs that have no HAS_ATTRIBUTE referrers
    # AND no historical TaskNode reference. We only delete safe BAs; otherwise
    # they linger as superseded but are no longer addressable.
    deleted_bas: List[str] = []
    try:
        for old_attr_fq in non_canonical:
            check = await neo4j.run_query(
                """
                MATCH (ba:BusinessAttribute {fq_name: $fq})
                OPTIONAL MATCH (e:BusinessEntity)-[:HAS_ATTRIBUTE]->(ba)
                OPTIONAL MATCH (t:TaskNode) WHERE $fq IN coalesce(t.canonical_entities, [])
                RETURN count(e) AS attr_links, count(t) AS task_refs
                """,
                {"fq": old_attr_fq},
                trace_id=trace_id,
            )
            if not check:
                continue
            attr_links = int(check[0].get("attr_links") or 0)
            task_refs = int(check[0].get("task_refs") or 0)
            if attr_links == 0 and task_refs == 0:
                await neo4j.run_query(
                    """
                    MATCH (ba:BusinessAttribute {fq_name: $fq})
                    DETACH DELETE ba
                    """,
                    {"fq": old_attr_fq},
                    trace_id=trace_id,
                )
                deleted_bas.append(old_attr_fq)
    except Exception as exc:
        logger.warning(
            "synonym non-canonical cleanup failed (non-fatal)",
            layer="router", error=str(exc), trace_id=trace_id,
        )

    # 5. Mark proposal applied.
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE synonym_proposals
               SET status = 'APPLIED',
                   chosen_canonical_attr   = %s,
                   chosen_canonical_column = %s,
                   reviewed_by = %s,
                   reviewed_at = NOW(3),
                   applied_at  = NOW(3)
             WHERE proposal_id = %s
            """,
            (chosen_attr, chosen_col, reviewed_by, proposal_id),
        )
        conn.commit()
    finally:
        conn.close()

    # 6. Audit-log.
    try:
        await _get_audit(settings).write(
            trace_id=trace_id,
            actor=reviewed_by,
            actor_type="USER",
            action="catalog.synonym_merge_applied",
            resource_type="synonym_proposals",
            resource_id=proposal_id,
            payload={
                "kind": proposal.get("kind"),
                "domain": proposal.get("domain"),
                "canonical_attr": chosen_attr,
                "canonical_column": chosen_col,
                "non_canonical": non_canonical,
                "deleted_bas": deleted_bas,
                "note": body.note,
            },
        )
    except Exception:
        pass

    # 7. Auto-resolve matching OPEN auditor_issues (kind=SYNONYM_AMBIGUITY).
    resolved_issue_ids: List[str] = []
    try:
        # Match by OR over every member fq_name appearing in resource_id.
        clauses = ["resource_id LIKE %s"] * len(members)
        params: List[Any] = [f"%{m}%" for m in members]
        if clauses:
            sql = f"""
            SELECT issue_id FROM auditor_issues
             WHERE status = 'OPEN'
               AND kind   = 'SYNONYM_AMBIGUITY'
               AND ({" OR ".join(clauses)})
            """
            cand_rows = _fetch(sql, tuple(params))
            issue_ids = [r["issue_id"] for r in cand_rows]
            if issue_ids:
                conn = _conn()
                try:
                    cur = conn.cursor()
                    placeholders = ",".join(["%s"] * len(issue_ids))
                    cur.execute(
                        f"""
                        UPDATE auditor_issues
                           SET status      = 'RESOLVED',
                               resolution  = %s,
                               resolved_by = %s,
                               resolved_at = NOW()
                         WHERE issue_id IN ({placeholders})
                        """,
                        tuple([f"Merged via proposal {proposal_id}", reviewed_by] + issue_ids),
                    )
                    conn.commit()
                    resolved_issue_ids = issue_ids
                finally:
                    conn.close()
    except Exception as exc:
        logger.warning(
            "synonym auditor_issues auto-resolve failed (non-fatal)",
            layer="router", error=str(exc), trace_id=trace_id,
        )

    return {
        "trace_id": trace_id,
        "proposal_id": proposal_id,
        "status": "APPLIED",
        "canonical_attr": chosen_attr,
        "canonical_column": chosen_col,
        "non_canonical": non_canonical,
        "deleted_bas": deleted_bas,
        "resolved_issue_ids": resolved_issue_ids,
    }


@router.post(
    "/consolidate",
    dependencies=[Depends(require_permission("catalog.write"))],
)
async def trigger_consolidation(
    request: Request,
    domain: Optional[str] = Query(None, description="If set, only cluster BAs in this domain"),
) -> Dict[str, Any]:
    """Manual trigger for the synonym consolidation pass (UI-driven)."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    neo4j = _get_neo4j(request)
    llm = _get_llm(request)
    if llm is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "LLM adapter not initialized", "trace_id": trace_id},
        )
    consolidator = SynonymConsolidator()
    summary = await consolidator.run(
        neo4j=neo4j, llm=llm, domain=domain, trace_id=trace_id,
    )
    return {"trace_id": trace_id, "summary": summary}
