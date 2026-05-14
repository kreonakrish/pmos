"""Financial Governance endpoints — token-cost reporting across every LLM
call made by orchestrator / translator / meta-assembly.

All data is sourced from pmos.llm_call_log, joined to:
  - pmos.agents              for agent_name, foundation_model
  - pmos.team_agents/teams   for team_name
  - pmos.conversations       for conversation title, intent (from metadata)
  - pmos.tool_execution_history for primary tool used per conversation
  - pmos.model_pricing       for editable per-MTok rates

Endpoints (all under /v1/finops):
  GET  /summary?period=24h|7d|30d|all       — KPI strip + trend + top breakdowns
  GET  /breakdown?group_by=...&period=...   — drill-down aggregator
  GET  /conversations?period=...            — top conversations by cost
  GET  /conversations/{conversation_id}     — per-call timeline for one conversation
  GET  /pricing                             — list model_pricing rows
  POST /pricing                             — add a price row
  PUT  /pricing/{pricing_id}                — edit a price row
  GET  /whatif?agent_id=&candidate_model=   — projected savings on agent model swap

Reads only — schema migrations live in infra/mysql/schema.sql.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

import mysql.connector
from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import settings
from app.utils.logger import logger


router = APIRouter(prefix="/v1/finops", tags=["finops"])


# ---------------------------------------------------------------------------
# MySQL helpers — short-lived sync connections, same pattern as ml_insights.py
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
        try:
            conn.close()
        except Exception:
            pass
    out: List[Dict[str, Any]] = []
    for r in rows:
        clean: Dict[str, Any] = {}
        for k, v in r.items():
            if v is None:
                clean[k] = None
            elif hasattr(v, "isoformat"):
                clean[k] = v.isoformat()
            elif hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
                # Decimal — convert to float for JSON
                clean[k] = float(v)
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


def _exec(sql: str, params: tuple = ()) -> int:
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid or cur.rowcount
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Period parsing
# ---------------------------------------------------------------------------
_PERIOD_HOURS = {"1h": 1, "24h": 24, "7d": 24 * 7, "30d": 24 * 30, "90d": 24 * 90}


def _period_clause(period: str) -> str:
    """Returns a SQL WHERE fragment like 'AND ts >= NOW() - INTERVAL 7 DAY'.
    Returns '' for period='all'."""
    if not period or period == "all":
        return ""
    hours = _PERIOD_HOURS.get(period)
    if hours is None:
        return ""
    return f"AND ts >= NOW() - INTERVAL {hours} HOUR"


# ---------------------------------------------------------------------------
# GET /v1/finops/summary
# ---------------------------------------------------------------------------
@router.get("/summary")
async def summary(
    request: Request,
    period: str = Query("7d", description="24h | 7d | 30d | 90d | all"),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    where = _period_clause(period)

    totals = _fetch(
        f"""
        SELECT
          COUNT(*)                                   AS n_calls,
          COALESCE(SUM(prompt_tokens), 0)            AS prompt_tokens,
          COALESCE(SUM(completion_tokens), 0)        AS completion_tokens,
          COALESCE(SUM(total_tokens), 0)             AS total_tokens,
          COALESCE(SUM(cost_usd), 0)                 AS cost_usd,
          COALESCE(AVG(latency_ms), 0)               AS avg_latency_ms,
          COUNT(DISTINCT conversation_id)            AS n_conversations,
          COUNT(DISTINCT user_id)                    AS n_users,
          COUNT(DISTINCT agent_id)                   AS n_agents
        FROM llm_call_log
        WHERE 1=1 {where}
        """
    )
    t = totals[0] if totals else {}

    # Daily trend (last 30 days regardless of period) — keeps the chart stable
    daily = _fetch(
        """
        SELECT DATE(ts) AS d,
               SUM(cost_usd) AS cost_usd,
               SUM(total_tokens) AS tokens,
               COUNT(*) AS n_calls
          FROM llm_call_log
         WHERE ts >= NOW() - INTERVAL 30 DAY
         GROUP BY DATE(ts)
         ORDER BY DATE(ts)
        """
    )

    by_provider = _fetch(
        f"""
        SELECT provider,
               SUM(cost_usd) AS cost_usd,
               SUM(total_tokens) AS tokens,
               COUNT(*) AS n_calls
          FROM llm_call_log
         WHERE 1=1 {where}
         GROUP BY provider
         ORDER BY cost_usd DESC
        """
    )

    by_service = _fetch(
        f"""
        SELECT service_name,
               SUM(cost_usd) AS cost_usd,
               SUM(total_tokens) AS tokens,
               COUNT(*) AS n_calls
          FROM llm_call_log
         WHERE 1=1 {where}
         GROUP BY service_name
         ORDER BY cost_usd DESC
        """
    )

    top_agents = _fetch(
        f"""
        SELECT l.agent_id,
               COALESCE(a.name, l.agent_id) AS agent_name,
               a.foundation_model,
               SUM(l.cost_usd) AS cost_usd,
               SUM(l.total_tokens) AS tokens,
               COUNT(*) AS n_calls
          FROM llm_call_log l
     LEFT JOIN agents a ON a.agent_id = l.agent_id OR (l.agent_id REGEXP '^[0-9]+$' AND a.id = CAST(l.agent_id AS UNSIGNED))
         WHERE l.agent_id IS NOT NULL {where.replace('ts', 'l.ts')}
         GROUP BY l.agent_id, a.name, a.foundation_model
         ORDER BY cost_usd DESC
         LIMIT 10
        """
    )

    top_models = _fetch(
        f"""
        SELECT provider, model,
               SUM(cost_usd) AS cost_usd,
               SUM(total_tokens) AS tokens,
               COUNT(*) AS n_calls
          FROM llm_call_log
         WHERE 1=1 {where}
         GROUP BY provider, model
         ORDER BY cost_usd DESC
         LIMIT 10
        """
    )

    top_users = _fetch(
        f"""
        SELECT user_id,
               COUNT(DISTINCT conversation_id) AS n_conversations,
               SUM(cost_usd) AS cost_usd,
               SUM(total_tokens) AS tokens,
               COUNT(*) AS n_calls
          FROM llm_call_log
         WHERE user_id IS NOT NULL {where}
         GROUP BY user_id
         ORDER BY cost_usd DESC
         LIMIT 10
        """
    )

    return {
        "trace_id": trace_id,
        "period": period,
        "totals": t,
        "daily_trend": daily,
        "by_provider": by_provider,
        "by_service": by_service,
        "top_agents": top_agents,
        "top_models": top_models,
        "top_users": top_users,
    }


# ---------------------------------------------------------------------------
# GET /v1/finops/breakdown — group-by aggregator
# ---------------------------------------------------------------------------
_GROUP_BY_COLUMNS = {
    "service": ("service_name", None, "service_name", "service_name"),
    "team": ("team_id", None, "team_id", "team_id"),
    "agent": ("agent_id", "agents", "agent_id", "name"),
    "model": ("model", None, "CONCAT(provider,'/',model)", "CONCAT(provider,'/',model)"),
    "provider": ("provider", None, "provider", "provider"),
    "user": ("user_id", None, "user_id", "user_id"),
    "conversation": ("conversation_id", "conversations", "conversation_id", "conversation_id"),
}


@router.get("/breakdown")
async def breakdown(
    request: Request,
    group_by: str = Query("service"),
    period: str = Query("7d"),
    service_name: Optional[str] = None,
    team_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    user_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    limit: int = Query(100, le=500),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    if group_by not in _GROUP_BY_COLUMNS:
        raise HTTPException(400, f"group_by must be one of {sorted(_GROUP_BY_COLUMNS)}")

    key_col, _, key_expr, label_expr = _GROUP_BY_COLUMNS[group_by]

    where_parts = ["1=1"]
    where_params: List[Any] = []
    period_clause = _period_clause(period).replace("AND ts", "AND l.ts")
    if period_clause:
        where_parts.append(period_clause.lstrip("AND "))
    if service_name:
        where_parts.append("l.service_name = %s")
        where_params.append(service_name)
    if team_id:
        where_parts.append("l.team_id = %s")
        where_params.append(team_id)
    if agent_id:
        where_parts.append("l.agent_id = %s")
        where_params.append(agent_id)
    if user_id:
        where_parts.append("l.user_id = %s")
        where_params.append(user_id)
    if conversation_id:
        where_parts.append("l.conversation_id = %s")
        where_params.append(conversation_id)
    if provider:
        where_parts.append("l.provider = %s")
        where_params.append(provider)
    if model:
        where_parts.append("l.model = %s")
        where_params.append(model)

    where_sql = " AND ".join(where_parts)

    # Optional join to enrich the label (e.g. agent_name for group_by=agent)
    join_sql = ""
    label_select = label_expr
    if group_by == "agent":
        join_sql = "LEFT JOIN agents a ON a.agent_id = l.agent_id OR (l.agent_id REGEXP '^[0-9]+$' AND a.id = CAST(l.agent_id AS UNSIGNED))"
        label_select = "COALESCE(a.name, l.agent_id)"

    sql = f"""
        SELECT l.{key_col} AS `key`,
               {label_select} AS label,
               SUM(l.cost_usd) AS cost_usd,
               SUM(l.total_tokens) AS tokens,
               SUM(l.prompt_tokens) AS prompt_tokens,
               SUM(l.completion_tokens) AS completion_tokens,
               COUNT(*) AS n_calls,
               AVG(l.latency_ms) AS avg_latency_ms,
               MIN(l.ts) AS first_seen,
               MAX(l.ts) AS last_seen
          FROM llm_call_log l
          {join_sql}
         WHERE {where_sql} AND l.{key_col} IS NOT NULL
         GROUP BY l.{key_col}, label
         ORDER BY cost_usd DESC
         LIMIT {int(limit)}
    """

    rows = _fetch(sql, tuple(where_params))
    return {
        "trace_id": trace_id,
        "group_by": group_by,
        "period": period,
        "filters": {
            "service_name": service_name, "team_id": team_id, "agent_id": agent_id,
            "user_id": user_id, "conversation_id": conversation_id,
            "provider": provider, "model": model,
        },
        "rows": rows,
        "count": len(rows),
    }


# ---------------------------------------------------------------------------
# GET /v1/finops/conversations
# ---------------------------------------------------------------------------
@router.get("/conversations")
async def conversations(
    request: Request,
    period: str = Query("7d"),
    order_by: str = Query("cost", description="cost | tokens | calls"),
    limit: int = Query(100, le=500),
    user_id: Optional[str] = None,
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    where = _period_clause(period).replace("AND ts", "AND l.ts")
    user_filter = ""
    params: List[Any] = []
    if user_id:
        user_filter = "AND l.user_id = %s"
        params.append(user_id)

    order_col = {"cost": "cost_usd", "tokens": "tokens", "calls": "n_calls"}.get(order_by, "cost_usd")

    sql = f"""
        SELECT l.conversation_id,
               c.user_id,
               c.team_id,
               c.title,
               COUNT(*)                  AS n_calls,
               SUM(l.total_tokens)       AS tokens,
               SUM(l.prompt_tokens)      AS prompt_tokens,
               SUM(l.completion_tokens)  AS completion_tokens,
               SUM(l.cost_usd)           AS cost_usd,
               MIN(l.ts)                 AS first_call_ts,
               MAX(l.ts)                 AS last_call_ts,
               MAX(l.trace_id)           AS sample_trace_id
          FROM llm_call_log l
     LEFT JOIN conversations c ON c.conversation_id = l.conversation_id
         WHERE l.conversation_id IS NOT NULL {where} {user_filter}
         GROUP BY l.conversation_id, c.user_id, c.team_id, c.title
         ORDER BY {order_col} DESC
         LIMIT {int(limit)}
    """
    rows = _fetch(sql, tuple(params))
    return {"trace_id": trace_id, "period": period, "rows": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# GET /v1/finops/conversations/{conversation_id}
# ---------------------------------------------------------------------------
@router.get("/conversations/{conversation_id}")
async def conversation_detail(conversation_id: str, request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    calls = _fetch(
        """
        SELECT l.call_id, l.ts, l.service_name, l.trace_id,
               l.agent_id, COALESCE(a.name, l.agent_id) AS agent_name,
               l.provider, l.model, l.prompt_tokens, l.completion_tokens,
               l.total_tokens, l.cost_usd, l.latency_ms, l.finish_reason,
               l.had_tool_calls, l.error
          FROM llm_call_log l
     LEFT JOIN agents a ON a.agent_id = l.agent_id OR (l.agent_id REGEXP '^[0-9]+$' AND a.id = CAST(l.agent_id AS UNSIGNED))
         WHERE l.conversation_id = %s
         ORDER BY l.ts ASC
        """,
        (conversation_id,),
    )

    summary_rows = _fetch(
        """
        SELECT COUNT(*) AS n_calls,
               SUM(prompt_tokens) AS prompt_tokens,
               SUM(completion_tokens) AS completion_tokens,
               SUM(total_tokens) AS total_tokens,
               SUM(cost_usd) AS cost_usd,
               COUNT(DISTINCT service_name) AS n_services,
               COUNT(DISTINCT agent_id) AS n_agents
          FROM llm_call_log
         WHERE conversation_id = %s
        """,
        (conversation_id,),
    )

    by_service = _fetch(
        """
        SELECT service_name, SUM(cost_usd) AS cost_usd, COUNT(*) AS n_calls
          FROM llm_call_log
         WHERE conversation_id = %s
         GROUP BY service_name
         ORDER BY cost_usd DESC
        """,
        (conversation_id,),
    )

    by_agent = _fetch(
        """
        SELECT l.agent_id, COALESCE(a.name, l.agent_id) AS agent_name,
               SUM(l.cost_usd) AS cost_usd, COUNT(*) AS n_calls
          FROM llm_call_log l
     LEFT JOIN agents a ON a.agent_id = l.agent_id OR (l.agent_id REGEXP '^[0-9]+$' AND a.id = CAST(l.agent_id AS UNSIGNED))
         WHERE l.conversation_id = %s AND l.agent_id IS NOT NULL
         GROUP BY l.agent_id, a.name
         ORDER BY cost_usd DESC
        """,
        (conversation_id,),
    )

    return {
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "summary": (summary_rows[0] if summary_rows else {}),
        "by_service": by_service,
        "by_agent": by_agent,
        "calls": calls,
    }


# ---------------------------------------------------------------------------
# GET /v1/finops/pricing
# ---------------------------------------------------------------------------
@router.get("/pricing")
async def list_pricing(request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    rows = _fetch(
        """
        SELECT pricing_id, provider, model, input_per_mtok, output_per_mtok,
               effective_from, notes, created_at, updated_at
          FROM model_pricing
         ORDER BY provider, model, effective_from DESC
        """
    )
    return {"trace_id": trace_id, "rows": rows, "count": len(rows)}


class PricingUpsertBody(BaseModel):
    provider: str
    model: str
    input_per_mtok: float
    output_per_mtok: float
    effective_from: Optional[str] = None  # ISO datetime; defaults to now
    notes: Optional[str] = None


@router.post("/pricing")
async def add_pricing(body: PricingUpsertBody, request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    eff = body.effective_from or None
    if eff:
        sql = """INSERT INTO model_pricing
                 (provider, model, input_per_mtok, output_per_mtok, effective_from, notes)
                 VALUES (%s, %s, %s, %s, %s, %s)"""
        params = (body.provider, body.model, body.input_per_mtok, body.output_per_mtok, eff, body.notes)
    else:
        sql = """INSERT INTO model_pricing
                 (provider, model, input_per_mtok, output_per_mtok, notes)
                 VALUES (%s, %s, %s, %s, %s)"""
        params = (body.provider, body.model, body.input_per_mtok, body.output_per_mtok, body.notes)

    try:
        new_id = _exec(sql, params)
    except mysql.connector.Error as exc:
        raise HTTPException(409, f"pricing insert failed: {exc}")
    logger.info("finops pricing added", layer="finops", pricing_id=new_id,
                provider=body.provider, model=body.model, trace_id=trace_id)
    return {"trace_id": trace_id, "pricing_id": new_id, "status": "created"}


@router.put("/pricing/{pricing_id}")
async def update_pricing(pricing_id: int, body: PricingUpsertBody, request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    _exec(
        """UPDATE model_pricing
              SET provider = %s, model = %s,
                  input_per_mtok = %s, output_per_mtok = %s,
                  notes = %s
            WHERE pricing_id = %s""",
        (body.provider, body.model, body.input_per_mtok, body.output_per_mtok,
         body.notes, pricing_id),
    )
    logger.info("finops pricing updated", layer="finops", pricing_id=pricing_id,
                trace_id=trace_id)
    return {"trace_id": trace_id, "pricing_id": pricing_id, "status": "updated"}


# ---------------------------------------------------------------------------
# GET /v1/finops/whatif — model-swap simulator
# ---------------------------------------------------------------------------
@router.get("/whatif")
async def whatif(
    request: Request,
    agent_id: str = Query(..., description="UUID of the agent to evaluate"),
    candidate_model: str = Query(..., description="Model to swap to (e.g. claude-haiku-4-5)"),
    period: str = Query("30d"),
) -> Dict[str, Any]:
    """Project monthly cost if this agent's foundation_model swaps to
    candidate_model, based on the agent's last-`period` token mix."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    # Pull agent's current model + accumulated token mix. The sandbox path
    # writes the integer agents.id into llm_call_log.agent_id (as a string)
    # while the rest of the orchestrator writes the UUID — so we match on
    # both forms via an IN-list, after resolving the int id once.
    agent_rows = _fetch(
        "SELECT id, name, foundation_model FROM agents WHERE agent_id = %s",
        (agent_id,),
    )
    if not agent_rows:
        raise HTTPException(404, f"agent {agent_id} not found")
    agent = agent_rows[0]
    current_model = agent.get("foundation_model")
    agent_id_keys = [agent_id]
    if agent.get("id") is not None:
        agent_id_keys.append(str(agent["id"]))

    where = _period_clause(period)
    placeholders = ",".join(["%s"] * len(agent_id_keys))
    mix_rows = _fetch(
        f"""
        SELECT COUNT(*)                          AS n_calls,
               COALESCE(SUM(prompt_tokens), 0)   AS prompt_tokens,
               COALESCE(SUM(completion_tokens),0) AS completion_tokens,
               COALESCE(SUM(cost_usd), 0)        AS current_cost_usd,
               MIN(ts)                            AS first_call,
               MAX(ts)                            AS last_call
          FROM llm_call_log
         WHERE agent_id IN ({placeholders}) {where}
        """,
        tuple(agent_id_keys),
    )
    mix = mix_rows[0] if mix_rows else {}

    # Look up pricing for current and candidate
    def _lookup_price(model: str) -> Dict[str, Any]:
        rows = _fetch(
            """SELECT provider, model, input_per_mtok, output_per_mtok, pricing_id
                 FROM model_pricing
                WHERE model = %s AND effective_from <= NOW()
                ORDER BY effective_from DESC LIMIT 1""",
            (model,),
        )
        return rows[0] if rows else {}

    current_price = _lookup_price(current_model) if current_model else {}
    candidate_price = _lookup_price(candidate_model)
    if not candidate_price:
        raise HTTPException(404, f"no pricing row for candidate model '{candidate_model}'")

    p_in = float(mix.get("prompt_tokens") or 0)
    p_out = float(mix.get("completion_tokens") or 0)

    def _cost(price: Dict[str, Any]) -> float:
        if not price:
            return 0.0
        return (p_in / 1_000_000) * float(price.get("input_per_mtok") or 0) + \
               (p_out / 1_000_000) * float(price.get("output_per_mtok") or 0)

    projected_current = _cost(current_price)
    projected_candidate = _cost(candidate_price)
    savings_usd = projected_current - projected_candidate
    savings_pct = (savings_usd / projected_current * 100.0) if projected_current > 0 else None

    return {
        "trace_id": trace_id,
        "agent_id": agent_id,
        "agent_name": agent.get("name"),
        "period": period,
        "n_calls_basis": int(mix.get("n_calls") or 0),
        "prompt_tokens_basis": int(p_in),
        "completion_tokens_basis": int(p_out),
        "current": {
            "model": current_model,
            "provider": current_price.get("provider"),
            "input_per_mtok": current_price.get("input_per_mtok"),
            "output_per_mtok": current_price.get("output_per_mtok"),
            "actual_cost_usd": float(mix.get("current_cost_usd") or 0),
            "projected_cost_usd": projected_current,
        },
        "candidate": {
            "model": candidate_model,
            "provider": candidate_price.get("provider"),
            "input_per_mtok": candidate_price.get("input_per_mtok"),
            "output_per_mtok": candidate_price.get("output_per_mtok"),
            "projected_cost_usd": projected_candidate,
        },
        "savings_usd": savings_usd,
        "savings_pct": savings_pct,
    }
