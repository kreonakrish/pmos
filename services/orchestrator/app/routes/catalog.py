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
from fastapi import APIRouter, BackgroundTasks, Body, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import settings
from app.services.crawler import run_crawler_async
from app.utils.logger import logger

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


@router.post("/crawlers")
async def create_crawler(
    request: Request,
    body: CreateCrawlerRequest,
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    crawler_id = str(uuid.uuid4())

    allowed = {"MYSQL", "POSTGRES", "SQLSERVER", "ORACLE", "TERADATA",
               "SNOWFLAKE", "GLUE", "S3", "EXCEL", "CSV", "SSRS_RDL"}
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


@router.post("/crawlers/{crawler_id}/run")
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
            RETURN c, ba.name AS attribute, ba.domain AS domain, ba.entity AS entity,
                   m.confidence AS confidence, m.status AS mapping_status
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
            WITH d, e, count(ba) AS attribute_count
            RETURN d.name AS domain,
                   collect(DISTINCT {entity: e.name, attributes: attribute_count}) AS entities
            """,
            {},
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error("ontology query failed", layer="router", error=str(exc), trace_id=trace_id)
        return {"trace_id": trace_id, "domains": [], "error": str(exc)}

    domains = []
    for r in (domain_rows or []):
        entities = [e for e in r.get("entities", []) if e and e.get("entity")]
        domains.append({
            "domain": r.get("domain"),
            "entities": entities,
        })
    return {"trace_id": trace_id, "domains": domains}


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


@router.post("/mapping-decisions/{decision_id}/review")
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

    # If the auditor corrected the mapping, update Neo4j so downstream lookups
    # see the new business-entity/attribute for this physical column.
    if status == "CORRECTED" or (status == "CONFIRMED" and (
        auditor_entity != decision.get("proposed_entity")
        or auditor_attribute != decision.get("proposed_attribute")
    )):
        neo4j = _get_neo4j(request)
        source_uri = decision.get("data_source") or ""
        data_asset = decision.get("data_asset") or ""
        data_column = decision.get("data_column") or ""

        # We don't store source_name directly in the audit row — reconstruct
        # by looking up the DataAsset whose fully_qualified matches.
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
            if asset_fq:
                col_fq = f"{asset_fq}.{data_column}"
                attr_fq = f"{auditor_domain}.{auditor_entity}.{auditor_attribute}"
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
                    MERGE (ba)-[m:MAPS_TO]->(c)
                    SET m.status = $status,
                        m.reviewed_by = $reviewed_by,
                        m.reviewed_at = datetime(),
                        m.confidence = 1.0
                    """,
                    {
                        "domain": auditor_domain,
                        "entity": auditor_entity,
                        "attr_fq": attr_fq,
                        "attr_name": auditor_attribute,
                        "col_fq": col_fq,
                        "status": status,
                        "reviewed_by": body.reviewed_by or "admin",
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
