"""Financial Governance — record every LLM call from the translator service.

Mirrors services/orchestrator/app/services/cost_recorder.py. Persists token
usage and cost per call to the shared pmos.llm_call_log table so the
orchestrator's /v1/finops endpoints can attribute spend across all services.

Design: never blocks the LLM response. All errors are swallowed and logged.
"""

from __future__ import annotations

import time
import uuid
from typing import Dict, Optional, Tuple

import mysql.connector

from app.config import settings
from app.utils.logger import logger


_PRICE_CACHE: Dict[Tuple[str, str], Tuple[float, float, Optional[int], float]] = {}
_PRICE_CACHE_TTL = 300.0


def _mysql_conn():
    return mysql.connector.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        database=settings.mysql_db,
        connection_timeout=5,
    )


def get_price(provider: str, model: str) -> Tuple[float, float, Optional[int]]:
    key = (provider or "", model or "")
    now = time.time()
    cached = _PRICE_CACHE.get(key)
    if cached and now - cached[3] < _PRICE_CACHE_TTL:
        return cached[0], cached[1], cached[2]

    try:
        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT input_per_mtok, output_per_mtok, pricing_id
                  FROM model_pricing
                 WHERE provider = %s AND model = %s AND effective_from <= NOW()
                 ORDER BY effective_from DESC
                 LIMIT 1
                """,
                (provider, model),
            )
            row = cur.fetchone()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("finops price lookup failed", layer="finops",
                       provider=provider, model=model, error=str(exc))
        return 0.0, 0.0, None

    if not row:
        logger.warning("finops no pricing row", layer="finops",
                       provider=provider, model=model)
        _PRICE_CACHE[key] = (0.0, 0.0, None, now)
        return 0.0, 0.0, None

    input_per_mtok = float(row[0] or 0)
    output_per_mtok = float(row[1] or 0)
    pricing_id = int(row[2]) if row[2] is not None else None
    _PRICE_CACHE[key] = (input_per_mtok, output_per_mtok, pricing_id, now)
    return input_per_mtok, output_per_mtok, pricing_id


async def record_llm_call(
    *,
    service_name: str = "translator",
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    trace_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    user_id: Optional[str] = None,
    team_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    tool_invocation_id: Optional[str] = None,
    latency_ms: Optional[int] = None,
    finish_reason: Optional[str] = None,
    had_tool_calls: bool = False,
    error: Optional[str] = None,
) -> None:
    try:
        prompt_tokens = int(prompt_tokens or 0)
        completion_tokens = int(completion_tokens or 0)
        total_tokens = prompt_tokens + completion_tokens

        input_per_mtok, output_per_mtok, pricing_id = get_price(provider, model)
        cost_usd = (
            (prompt_tokens / 1_000_000.0) * input_per_mtok
            + (completion_tokens / 1_000_000.0) * output_per_mtok
        )

        conn = _mysql_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO llm_call_log
                  (call_id, service_name, trace_id, conversation_id, user_id,
                   team_id, agent_id, tool_invocation_id, provider, model,
                   prompt_tokens, completion_tokens, total_tokens, cost_usd,
                   pricing_id, latency_ms, finish_reason, had_tool_calls, error)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    str(uuid.uuid4()),
                    service_name,
                    trace_id,
                    conversation_id,
                    user_id,
                    team_id,
                    agent_id,
                    tool_invocation_id,
                    provider or "unknown",
                    model or "unknown",
                    prompt_tokens,
                    completion_tokens,
                    total_tokens,
                    round(cost_usd, 6),
                    pricing_id,
                    int(latency_ms) if latency_ms is not None else None,
                    finish_reason,
                    1 if had_tool_calls else 0,
                    (error[:1000] if error else None),
                ),
            )
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("finops record_llm_call failed", layer="finops",
                       provider=provider, model=model, error=str(exc),
                       trace_id=trace_id)
