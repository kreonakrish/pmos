"""ML Insights endpoints — operator visibility into the learning loop.

Exposes:
  GET  /v1/ml/bandits/summary                  — aggregate stats + ready-for-LIVE
  GET  /v1/ml/bandits/state                    — per-(agent, context) Beta state
  GET  /v1/ml/bandits/decisions                — recent decision log
  GET  /v1/ml/bandits/convergence              — posterior mean over time
  GET  /v1/ml/embeddings/summary               — node count, dim, algorithm, freshness
  GET  /v1/ml/embeddings/projection            — 2D PCA projection of embeddings
  GET  /v1/ml/embeddings/similar               — k-nearest neighbors by cosine
  GET  /v1/ml/learned-scorer/summary           — active model + shadow prediction stats
  GET  /v1/ml/learned-scorer/predictions       — recent shadow predictions
  GET  /v1/ml/sops/proposals                   — pending/promoted SOP proposals
  POST /v1/ml/sops/proposals/{id}/promote      — promote an SOP proposal
  POST /v1/ml/sops/proposals/{id}/reject       — reject an SOP proposal

All queries are read-only against pmos MySQL tables populated by the bandit
selector, the Node2Vec job, the learned scorer shadow log, and the SOP
discovery job. The orchestrator container has no numpy, so PCA is done in
pure-Python power iteration.
"""

from __future__ import annotations

import json
import math
import random
import uuid
from typing import Any, Dict, List, Optional, Tuple

import mysql.connector
from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import settings
from app.utils.logger import logger

router = APIRouter(prefix="/v1/ml", tags=["ml-insights"])


# ---------------------------------------------------------------------------
# MySQL helpers (short-lived sync connections, same pattern as governance.py)
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


# ---------------------------------------------------------------------------
# Bandit constants — mirror bandit_selector.py
# ---------------------------------------------------------------------------
MIN_PULLS_FOR_LIVE = 20
PRIOR_MEAN = 0.6
PRIOR_STRENGTH = 10.0


def _posterior_mean(alpha: float, beta: float) -> float:
    if alpha + beta <= 0:
        return PRIOR_MEAN
    return alpha / (alpha + beta)


def _credible_interval(alpha: float, beta: float) -> Tuple[float, float]:
    """95% credible interval on a Beta(alpha, beta), via Wilson-like normal
    approximation on the mean — good enough for a UI bar, avoids scipy.
    """
    if alpha + beta <= 0:
        return (0.0, 1.0)
    mean = _posterior_mean(alpha, beta)
    var = (alpha * beta) / (((alpha + beta) ** 2) * (alpha + beta + 1))
    sd = math.sqrt(max(var, 0.0))
    lo = max(0.0, mean - 1.96 * sd)
    hi = min(1.0, mean + 1.96 * sd)
    return (lo, hi)


# ---------------------------------------------------------------------------
# GET /v1/ml/bandits/summary
# ---------------------------------------------------------------------------
@router.get("/bandits/summary")
async def bandits_summary(request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    totals = _fetch(
        """
        SELECT
          COUNT(*)                               AS total_decisions,
          SUM(reward IS NOT NULL)                AS rewarded,
          SUM(mode = 'SHADOW')                   AS shadow,
          SUM(mode = 'LIVE')                     AS live,
          SUM(mode = 'EXPLORATION')              AS exploration,
          SUM(mode = 'FALLBACK')                 AS fallback,
          SUM(bandit_pick_agent_id <> selected_agent_id) AS disagreements
        FROM bandit_decisions
        """,
    )
    total_stats = totals[0] if totals else {}

    state_totals = _fetch(
        """
        SELECT
          COUNT(*)            AS state_rows,
          COUNT(DISTINCT agent_id)         AS agents_tracked,
          COUNT(DISTINCT context_bucket)   AS contexts_tracked,
          COALESCE(MAX(pulls),0)          AS max_pulls,
          COALESCE(SUM(pulls),0)          AS total_pulls
        FROM bandit_agent_state
        """,
    )
    state_stats = state_totals[0] if state_totals else {}

    # Ready-for-LIVE readiness per context bucket: a context is "READY" when
    # every arm in it has at least MIN_PULLS_FOR_LIVE pulls.
    readiness_rows = _fetch(
        """
        SELECT
          context_bucket,
          COUNT(*)         AS arms,
          MIN(pulls)       AS min_pulls,
          MAX(pulls)       AS max_pulls,
          AVG(pulls)       AS avg_pulls
        FROM bandit_agent_state
        GROUP BY context_bucket
        ORDER BY min_pulls DESC, avg_pulls DESC
        """,
    )
    readiness: List[Dict[str, Any]] = []
    for r in readiness_rows:
        min_pulls = r.get("min_pulls") or 0
        state = "READY" if min_pulls >= MIN_PULLS_FOR_LIVE else (
            "WARMING" if min_pulls >= MIN_PULLS_FOR_LIVE // 2 else "COLD"
        )
        readiness.append({
            "context_bucket": r["context_bucket"],
            "arms": r.get("arms") or 0,
            "min_pulls": min_pulls,
            "max_pulls": r.get("max_pulls") or 0,
            "avg_pulls": float(r.get("avg_pulls") or 0),
            "state": state,
        })

    return {
        "trace_id": trace_id,
        "prior": {"mean": PRIOR_MEAN, "strength": PRIOR_STRENGTH},
        "min_pulls_for_live": MIN_PULLS_FOR_LIVE,
        "decisions": {
            "total": total_stats.get("total_decisions") or 0,
            "rewarded": total_stats.get("rewarded") or 0,
            "shadow": total_stats.get("shadow") or 0,
            "live": total_stats.get("live") or 0,
            "exploration": total_stats.get("exploration") or 0,
            "fallback": total_stats.get("fallback") or 0,
            "disagreements": total_stats.get("disagreements") or 0,
        },
        "state": {
            "rows": state_stats.get("state_rows") or 0,
            "agents_tracked": state_stats.get("agents_tracked") or 0,
            "contexts_tracked": state_stats.get("contexts_tracked") or 0,
            "max_pulls": state_stats.get("max_pulls") or 0,
            "total_pulls": state_stats.get("total_pulls") or 0,
        },
        "readiness": readiness,
    }


# ---------------------------------------------------------------------------
# GET /v1/ml/bandits/state
# ---------------------------------------------------------------------------
@router.get("/bandits/state")
async def bandits_state(
    request: Request,
    context_bucket: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    where = ""
    params: tuple = ()
    if context_bucket:
        where = "WHERE context_bucket = %s"
        params = (context_bucket,)

    rows = _fetch(
        f"""
        SELECT agent_id, agent_name, context_bucket,
               alpha, beta, pulls, total_reward, last_updated, created_at
        FROM bandit_agent_state
        {where}
        ORDER BY pulls DESC, last_updated DESC
        LIMIT {int(limit)}
        """,
        params,
    )

    enriched = []
    for r in rows:
        alpha = float(r["alpha"])
        beta_v = float(r["beta"])
        mean = _posterior_mean(alpha, beta_v)
        lo, hi = _credible_interval(alpha, beta_v)
        enriched.append({
            **r,
            "posterior_mean": mean,
            "credible_low": lo,
            "credible_high": hi,
            "ready": r.get("pulls", 0) >= MIN_PULLS_FOR_LIVE,
        })
    return {"trace_id": trace_id, "state": enriched, "count": len(enriched)}


# ---------------------------------------------------------------------------
# GET /v1/ml/bandits/decisions
# ---------------------------------------------------------------------------
@router.get("/bandits/decisions")
async def bandits_decisions(
    request: Request,
    mode: Optional[str] = Query(None),
    disagreements_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    where_clauses: List[str] = []
    params_list: List[Any] = []
    if mode:
        where_clauses.append("mode = %s")
        params_list.append(mode.upper())
    if disagreements_only:
        where_clauses.append("bandit_pick_agent_id <> selected_agent_id")
    where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    rows = _fetch(
        f"""
        SELECT decision_id, trace_id, session_id, graph_id, node_id,
               context_bucket, mode,
               selected_agent_id, selected_agent_name,
               bandit_pick_agent_id, bandit_pick_agent_name,
               candidate_agents, reward, reward_recorded_at, created_at
        FROM bandit_decisions
        {where}
        ORDER BY created_at DESC
        LIMIT {int(limit)}
        """,
        tuple(params_list),
    )

    for r in rows:
        r["disagreement"] = (
            r.get("bandit_pick_agent_id") and r.get("selected_agent_id")
            and r["bandit_pick_agent_id"] != r["selected_agent_id"]
        )
    return {"trace_id": trace_id, "decisions": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# GET /v1/ml/bandits/convergence
# ---------------------------------------------------------------------------
@router.get("/bandits/convergence")
async def bandits_convergence(
    request: Request,
    agent_id: str = Query(...),
    context_bucket: str = Query(...),
    limit: int = Query(200, ge=1, le=1000),
) -> Dict[str, Any]:
    """Reconstruct the posterior-mean trajectory for one (agent, context)
    pair by replaying the reward history chronologically.
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    rows = _fetch(
        """
        SELECT decision_id, reward, reward_recorded_at, created_at
        FROM bandit_decisions
        WHERE selected_agent_id = %s AND context_bucket = %s AND reward IS NOT NULL
        ORDER BY COALESCE(reward_recorded_at, created_at) ASC
        LIMIT %s
        """,
        (agent_id, context_bucket, int(limit)),
    )

    alpha = 1.0 + PRIOR_MEAN * PRIOR_STRENGTH
    beta = 1.0 + (1.0 - PRIOR_MEAN) * PRIOR_STRENGTH
    series: List[Dict[str, Any]] = []
    for i, r in enumerate(rows):
        rv = float(r["reward"])
        alpha += rv
        beta += 1.0 - rv
        series.append({
            "i": i + 1,
            "ts": r.get("reward_recorded_at") or r.get("created_at"),
            "reward": rv,
            "alpha": alpha,
            "beta": beta,
            "posterior_mean": _posterior_mean(alpha, beta),
        })

    return {
        "trace_id": trace_id,
        "agent_id": agent_id,
        "context_bucket": context_bucket,
        "series": series,
        "count": len(series),
    }


# ---------------------------------------------------------------------------
# GET /v1/ml/embeddings/summary
# ---------------------------------------------------------------------------
@router.get("/embeddings/summary")
async def embeddings_summary(request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    rows = _fetch(
        """
        SELECT COUNT(*)               AS total,
               COUNT(DISTINCT graph_id) AS graphs,
               MIN(computed_at)       AS first_computed,
               MAX(computed_at)       AS last_computed,
               MIN(dim)               AS min_dim,
               MAX(dim)               AS max_dim,
               MIN(algorithm)         AS algorithm
        FROM task_node_embeddings
        """,
    )
    summary = rows[0] if rows else {}

    node_type_rows = _fetch(
        """
        SELECT COALESCE(node_type,'(null)') AS node_type, COUNT(*) AS n
        FROM task_node_embeddings
        GROUP BY node_type
        ORDER BY n DESC
        """,
    )

    return {
        "trace_id": trace_id,
        "total": summary.get("total") or 0,
        "graphs": summary.get("graphs") or 0,
        "first_computed": summary.get("first_computed"),
        "last_computed": summary.get("last_computed"),
        "dim": summary.get("max_dim") or 0,
        "algorithm": summary.get("algorithm") or "",
        "by_node_type": node_type_rows,
    }


# ---------------------------------------------------------------------------
# Pure-Python PCA (no numpy) — power iteration on the centered covariance.
# ---------------------------------------------------------------------------
def _pca_2d(vectors: List[List[float]]) -> List[Tuple[float, float]]:
    n = len(vectors)
    if n == 0:
        return []
    d = len(vectors[0])
    if d == 0:
        return [(0.0, 0.0) for _ in vectors]

    # Center the columns
    mean = [0.0] * d
    for v in vectors:
        for i in range(d):
            mean[i] += v[i]
    mean = [m / n for m in mean]
    centered = [[v[i] - mean[i] for i in range(d)] for v in vectors]

    def norm(v: List[float]) -> float:
        return math.sqrt(sum(x * x for x in v)) or 1e-12

    def power_iter(exclude: Optional[List[List[float]]] = None, iters: int = 40) -> List[float]:
        rng = random.Random(42)
        v = [rng.random() - 0.5 for _ in range(d)]
        n0 = norm(v)
        v = [x / n0 for x in v]
        for _ in range(iters):
            # X v  (n-vector)
            xv = [sum(row[i] * v[i] for i in range(d)) for row in centered]
            # X^T (X v)  (d-vector)
            xtxv = [0.0] * d
            for j in range(n):
                c = xv[j]
                row = centered[j]
                for i in range(d):
                    xtxv[i] += row[i] * c
            # Deflate against excluded directions (Gram–Schmidt)
            if exclude:
                for e in exclude:
                    dot = sum(xtxv[i] * e[i] for i in range(d))
                    for i in range(d):
                        xtxv[i] -= dot * e[i]
            nn = norm(xtxv)
            v = [x / nn for x in xtxv]
        return v

    pc1 = power_iter()
    pc2 = power_iter(exclude=[pc1])

    projected: List[Tuple[float, float]] = []
    for row in centered:
        x = sum(row[i] * pc1[i] for i in range(d))
        y = sum(row[i] * pc2[i] for i in range(d))
        projected.append((x, y))
    return projected


# ---------------------------------------------------------------------------
# GET /v1/ml/embeddings/projection
# ---------------------------------------------------------------------------
@router.get("/embeddings/projection")
async def embeddings_projection(
    request: Request,
    limit: int = Query(500, ge=10, le=2000),
    node_type: Optional[str] = Query(None),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    where = ""
    params: tuple = ()
    if node_type:
        where = "WHERE node_type = %s"
        params = (node_type,)

    rows = _fetch(
        f"""
        SELECT node_id, graph_id, node_type, embedding
        FROM task_node_embeddings
        {where}
        ORDER BY computed_at DESC
        LIMIT {int(limit)}
        """,
        params,
    )
    if not rows:
        return {"trace_id": trace_id, "points": [], "algorithm": "pca2d", "count": 0}

    vectors: List[List[float]] = []
    meta: List[Dict[str, Any]] = []
    for r in rows:
        emb = r.get("embedding")
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except Exception:
                continue
        if not isinstance(emb, list) or not emb:
            continue
        vectors.append([float(x) for x in emb])
        meta.append({
            "node_id": r["node_id"],
            "graph_id": r.get("graph_id"),
            "node_type": r.get("node_type") or "",
        })

    try:
        proj = _pca_2d(vectors)
    except Exception as exc:
        logger.warning("PCA failed", layer="router", error=str(exc), trace_id=trace_id)
        proj = [(0.0, 0.0)] * len(vectors)

    points = [
        {
            "node_id": meta[i]["node_id"],
            "graph_id": meta[i]["graph_id"],
            "node_type": meta[i]["node_type"],
            "x": proj[i][0],
            "y": proj[i][1],
        }
        for i in range(len(vectors))
    ]
    return {"trace_id": trace_id, "points": points, "algorithm": "pca2d", "count": len(points)}


# ---------------------------------------------------------------------------
# GET /v1/ml/embeddings/similar
# ---------------------------------------------------------------------------
@router.get("/embeddings/similar")
async def embeddings_similar(
    request: Request,
    node_id: str = Query(...),
    k: int = Query(10, ge=1, le=50),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    base_rows = _fetch(
        "SELECT node_id, graph_id, node_type, embedding FROM task_node_embeddings WHERE node_id = %s",
        (node_id,),
    )
    if not base_rows:
        raise HTTPException(
            status_code=404,
            detail={"error": "node_id not found in embeddings", "node_id": node_id, "trace_id": trace_id},
        )

    base_emb = base_rows[0]["embedding"]
    if isinstance(base_emb, str):
        base_emb = json.loads(base_emb)
    base_vec = [float(x) for x in base_emb]
    base_norm = math.sqrt(sum(x * x for x in base_vec)) or 1e-12

    # Pull a working set — cap at 5000 to keep pure-Python dot products snappy.
    others = _fetch(
        """
        SELECT node_id, graph_id, node_type, embedding
        FROM task_node_embeddings
        WHERE node_id <> %s
        ORDER BY computed_at DESC
        LIMIT 5000
        """,
        (node_id,),
    )

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for r in others:
        emb = r["embedding"]
        if isinstance(emb, str):
            try:
                emb = json.loads(emb)
            except Exception:
                continue
        if not isinstance(emb, list) or len(emb) != len(base_vec):
            continue
        v = [float(x) for x in emb]
        dot = sum(base_vec[i] * v[i] for i in range(len(base_vec)))
        vnorm = math.sqrt(sum(x * x for x in v)) or 1e-12
        cos = dot / (base_norm * vnorm)
        scored.append((cos, {
            "node_id": r["node_id"],
            "graph_id": r.get("graph_id"),
            "node_type": r.get("node_type"),
            "similarity": cos,
        }))
    scored.sort(key=lambda t: t[0], reverse=True)

    return {
        "trace_id": trace_id,
        "reference": {
            "node_id": base_rows[0]["node_id"],
            "graph_id": base_rows[0].get("graph_id"),
            "node_type": base_rows[0].get("node_type"),
        },
        "neighbors": [s[1] for s in scored[:k]],
    }


# ---------------------------------------------------------------------------
# Learned Scorer (1B) endpoints
# ---------------------------------------------------------------------------
@router.get("/learned-scorer/summary")
async def learned_scorer_summary(request: Request) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    active_rows = _fetch(
        """
        SELECT model_version, algorithm, n_features, n_samples, n_positive,
               n_synthetic, n_real, train_accuracy, val_accuracy, val_auc,
               weights_path, notes, is_active, created_at, feature_names
        FROM learned_scorer_models
        WHERE is_active = TRUE
        ORDER BY created_at DESC LIMIT 1
        """,
    )
    active = active_rows[0] if active_rows else None

    all_models = _fetch(
        """
        SELECT model_version, algorithm, n_samples, val_accuracy, val_auc,
               is_active, created_at
        FROM learned_scorer_models
        ORDER BY created_at DESC LIMIT 10
        """,
    )

    # Shadow prediction aggregates
    pred_stats_rows = _fetch(
        """
        SELECT
          COUNT(*)                                               AS total,
          COUNT(user_feedback)                                   AS labeled,
          AVG(learned_score)                                     AS avg_learned,
          AVG(heuristic_score)                                   AS avg_heuristic,
          AVG(ABS(learned_score - heuristic_score))              AS mae_vs_heuristic,
          SUM(user_feedback = 'positive')                        AS positive,
          SUM(user_feedback = 'negative')                        AS negative
        FROM learned_scorer_predictions
        """,
    )
    pred_stats = pred_stats_rows[0] if pred_stats_rows else {}

    # Current w7 weight
    weight_rows = _fetch(
        """
        SELECT parameter_value, auto_adjust, updated_at
        FROM scoring_weights
        WHERE scope_type='GLOBAL' AND parameter_name='w7_learned_quality'
        LIMIT 1
        """,
    )
    weight = weight_rows[0] if weight_rows else {"parameter_value": 0.0}

    return {
        "trace_id": trace_id,
        "active_model": active,
        "models": all_models,
        "prediction_stats": {
            "total": pred_stats.get("total") or 0,
            "labeled": pred_stats.get("labeled") or 0,
            "avg_learned": float(pred_stats.get("avg_learned") or 0.0),
            "avg_heuristic": float(pred_stats.get("avg_heuristic") or 0.0),
            "mae_vs_heuristic": float(pred_stats.get("mae_vs_heuristic") or 0.0),
            "positive_labels": pred_stats.get("positive") or 0,
            "negative_labels": pred_stats.get("negative") or 0,
        },
        "w7_learned_quality": {
            "value": float(weight.get("parameter_value") or 0.0),
            "auto_adjust": bool(weight.get("auto_adjust")) if weight.get("auto_adjust") is not None else None,
            "updated_at": weight.get("updated_at"),
            "mode": "LIVE" if float(weight.get("parameter_value") or 0.0) > 0 else "SHADOW",
        },
    }


@router.get("/learned-scorer/predictions")
async def learned_scorer_predictions(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
    labeled_only: bool = Query(False),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    where = "WHERE user_feedback IS NOT NULL" if labeled_only else ""
    rows = _fetch(
        f"""
        SELECT prediction_id, model_version, trace_id, session_id,
               graph_id, node_id, agent_id, agent_name,
               heuristic_score, learned_score, user_feedback,
               features, created_at
        FROM learned_scorer_predictions
        {where}
        ORDER BY created_at DESC
        LIMIT {int(limit)}
        """,
    )
    for r in rows:
        h = r.get("heuristic_score")
        l = r.get("learned_score")
        if h is not None and l is not None:
            r["delta"] = float(l) - float(h)
    return {"trace_id": trace_id, "predictions": rows, "count": len(rows)}


# ---------------------------------------------------------------------------
# SOP Discovery (2D) endpoints
# ---------------------------------------------------------------------------
@router.get("/sops/proposals")
async def sops_proposals(
    request: Request,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    where = ""
    params: tuple = ()
    if status:
        where = "WHERE status = %s"
        params = (status.upper(),)
    rows = _fetch(
        f"""
        SELECT proposal_id, cluster_size, avg_score,
               best_agent_id, best_agent_name,
               summary, sample_messages, keywords,
               status, promoted_sop_id, reviewed_by, reviewed_at, created_at
        FROM sop_proposals
        {where}
        ORDER BY
          (status='PENDING') DESC,
          cluster_size DESC,
          created_at DESC
        LIMIT {int(limit)}
        """,
        params,
    )
    return {"trace_id": trace_id, "proposals": rows, "count": len(rows)}


class SOPReviewRequest(BaseModel):
    reviewed_by: Optional[str] = "admin"
    note: Optional[str] = ""


@router.post("/sops/proposals/{proposal_id}/promote")
async def sops_promote(
    proposal_id: str,
    request: Request,
    body: SOPReviewRequest = Body(default=SOPReviewRequest()),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))

    # Load the proposal
    rows = _fetch(
        "SELECT * FROM sop_proposals WHERE proposal_id=%s",
        (proposal_id,),
    )
    if not rows:
        raise HTTPException(
            status_code=404,
            detail={"error": "proposal not found", "proposal_id": proposal_id, "trace_id": trace_id},
        )
    prop = rows[0]
    if prop.get("status") == "PROMOTED":
        return {"trace_id": trace_id, "proposal": prop, "already_promoted": True}

    # Create SOPNode in Neo4j
    neo4j = request.app.state.neo4j
    sop_id = f"sop-{proposal_id[:8]}"
    try:
        await neo4j.run_query(
            """
            CREATE (s:SOPNode {
              sop_id: $sop_id,
              title: $title,
              keywords: $keywords,
              cluster_size: $cluster_size,
              avg_score: $avg_score,
              best_agent_name: $best_agent_name,
              source: 'auto_discovery',
              source_proposal_id: $proposal_id,
              created_at: datetime()
            })
            RETURN s
            """,
            {
                "sop_id": sop_id,
                "title": prop.get("summary", "")[:200],
                "keywords": prop.get("keywords") if isinstance(prop.get("keywords"), list) else [],
                "cluster_size": prop.get("cluster_size") or 0,
                "avg_score": float(prop.get("avg_score") or 0.0),
                "best_agent_name": prop.get("best_agent_name") or "",
                "proposal_id": proposal_id,
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.error(
            "SOP promote: Neo4j write failed",
            layer="router",
            error=str(exc),
            trace_id=trace_id,
        )
        raise HTTPException(
            status_code=500,
            detail={"error": f"Neo4j write failed: {exc}", "trace_id": trace_id},
        )

    # Flip the MySQL row
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE sop_proposals
               SET status='PROMOTED',
                   promoted_sop_id=%s,
                   reviewed_by=%s,
                   reviewed_at=NOW()
             WHERE proposal_id=%s
            """,
            (sop_id, body.reviewed_by, proposal_id),
        )
        conn.commit()
    finally:
        conn.close()

    return {"trace_id": trace_id, "proposal_id": proposal_id, "sop_id": sop_id, "status": "PROMOTED"}


@router.post("/sops/proposals/{proposal_id}/reject")
async def sops_reject(
    proposal_id: str,
    request: Request,
    body: SOPReviewRequest = Body(default=SOPReviewRequest()),
) -> Dict[str, Any]:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE sop_proposals
               SET status='REJECTED',
                   reviewed_by=%s,
                   reviewed_at=NOW()
             WHERE proposal_id=%s
            """,
            (body.reviewed_by, proposal_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail={"error": "proposal not found", "proposal_id": proposal_id, "trace_id": trace_id},
            )
        conn.commit()
    finally:
        conn.close()
    return {"trace_id": trace_id, "proposal_id": proposal_id, "status": "REJECTED"}
