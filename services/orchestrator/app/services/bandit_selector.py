"""Contextual bandit agent selection (1A).

Thompson Sampling over per-(agent, context_bucket) Beta distributions.

Usage inside the pipeline:

    from app.services.bandit_selector import BanditSelector
    bandit = BanditSelector()  # created once and reused

    # In _step3_negotiate, right after negotiation returns a winner:
    decision = bandit.select(
        candidates=team_agents,
        context_bucket=f"team:{team_id}|type:{task_type}",
        actual_winner_id=neg_result.winner.agent_id if neg_result.winner else None,
        trace_id=trace_id,
        session_id=session_id,
        graph_id=graph_id,
        node_id=node_id,
        mode="SHADOW",
    )

    # After scoring completes for that node:
    bandit.record_reward(decision_id, reward=score_0_to_1, trace_id=trace_id)

Modes:
  SHADOW      - bandit logs what it WOULD pick; actual selection unchanged
  LIVE        - bandit's pick IS the selection
  EXPLORATION - 10% random-agent pick to keep under-pulled arms refreshed
  FALLBACK    - bandit had no confident choice; deferred to caller

The module is designed to be dependency-light: it uses the orchestrator's
existing settings to open a short-lived mysql.connector connection on each call.
At PMOS's current decision rate (~1 per conversation turn) this is trivially
fast. If it ever becomes a hotspot, swap to aiomysql with a pool.
"""

from __future__ import annotations

import json
import random
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import mysql.connector

from app.config import settings
from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Config — simple module-level constants, tuneable without code changes via env
# ---------------------------------------------------------------------------
MIN_PULLS_FOR_LIVE = 20          # below this, bandit is not trusted as primary
EXPLORATION_EPSILON = 0.10       # 10% forced exploration on any decision
DEFAULT_ALPHA = 1.0              # Beta prior — uniform = Beta(1,1)
DEFAULT_BETA = 1.0
PRIOR_MEAN = 0.6                 # per user spec: start bandits assuming 60% success
PRIOR_STRENGTH = 10.0            # equivalent sample size of the prior


@dataclass
class BanditDecision:
    decision_id: str
    context_bucket: str
    selected_agent_id: str
    selected_agent_name: str
    bandit_pick_agent_id: str
    bandit_pick_agent_name: str
    mode: str
    candidates: List[Dict[str, Any]]
    trace_id: str


class BanditSelector:
    """Thompson Sampling bandit over Beta(alpha, beta) per (agent, context).

    Creates MySQL rows lazily. Thread/async-safe at the MySQL level since each
    call opens a fresh connection.
    """

    def __init__(self) -> None:
        self._rng = random.Random()

    # --------------------------------------------------------------------
    # MySQL helpers
    # --------------------------------------------------------------------
    def _conn(self):
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_db,
            connection_timeout=5,
        )

    def _load_state(
        self,
        agent_ids: List[str],
        context_bucket: str,
    ) -> Dict[str, Dict[str, float]]:
        """Return {agent_id: {alpha, beta, pulls, total_reward}}.

        Missing rows default to the PRIOR_MEAN-seeded Beta — not the uniform
        Beta(1,1) — because the user asked us to start at a 60% baseline.
        """
        if not agent_ids:
            return {}
        placeholders = ",".join(["%s"] * len(agent_ids))
        sql = (
            f"SELECT agent_id, alpha, beta, pulls, total_reward "
            f"FROM bandit_agent_state "
            f"WHERE context_bucket = %s AND agent_id IN ({placeholders})"
        )
        state: Dict[str, Dict[str, float]] = {}
        try:
            conn = self._conn()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(sql, (context_bucket, *agent_ids))
                for row in cur.fetchall() or []:
                    state[row["agent_id"]] = {
                        "alpha": float(row["alpha"]),
                        "beta": float(row["beta"]),
                        "pulls": int(row["pulls"]),
                        "total_reward": float(row["total_reward"]),
                    }
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "Bandit state load failed; using priors",
                layer="service",
                error=str(exc),
                context_bucket=context_bucket,
            )

        prior_alpha = DEFAULT_ALPHA + PRIOR_MEAN * PRIOR_STRENGTH
        prior_beta = DEFAULT_BETA + (1.0 - PRIOR_MEAN) * PRIOR_STRENGTH
        for aid in agent_ids:
            state.setdefault(aid, {
                "alpha": prior_alpha,
                "beta": prior_beta,
                "pulls": 0,
                "total_reward": 0.0,
            })
        return state

    # --------------------------------------------------------------------
    # Core: select()
    # --------------------------------------------------------------------
    def select(
        self,
        candidates: List[Any],
        context_bucket: str,
        actual_winner_id: Optional[str] = None,
        actual_winner_name: str = "",
        trace_id: str = "",
        session_id: str = "",
        graph_id: str = "",
        node_id: str = "",
        mode: str = "SHADOW",
    ) -> Optional[BanditDecision]:
        """Sample each candidate's Beta, pick argmax, log the decision.

        If mode='SHADOW', the caller's actual_winner_id is recorded as the
        authoritative selection and the bandit's pick is stored alongside for
        later comparison. If mode='LIVE', the bandit's pick IS the selection.

        Returns the BanditDecision so the caller can hold onto decision_id
        and later call record_reward(). Returns None if candidates is empty.
        """
        if not candidates:
            return None

        # Normalize candidates into (id, name) tuples; accepts dataclass Agent
        # or BidResponse or raw dicts with keys agent_id/name.
        pairs: List[tuple] = []
        for c in candidates:
            if hasattr(c, "agent_id"):
                aid = str(getattr(c, "agent_id", "") or "")
                aname = str(getattr(c, "name", "") or getattr(c, "agent_name", "") or "")
            elif isinstance(c, dict):
                aid = str(c.get("agent_id", "") or c.get("id", "") or "")
                aname = str(c.get("name", "") or c.get("agent_name", "") or "")
            else:
                continue
            if aid:
                pairs.append((aid, aname))

        if not pairs:
            return None

        agent_ids = [p[0] for p in pairs]
        state = self._load_state(agent_ids, context_bucket)

        # Optional forced exploration
        forced = self._rng.random() < EXPLORATION_EPSILON
        sampled: List[Dict[str, Any]] = []
        for aid, aname in pairs:
            s = state[aid]
            try:
                theta = float(self._rng.betavariate(s["alpha"], s["beta"]))
            except Exception:
                theta = PRIOR_MEAN
            sampled.append({
                "agent_id": aid,
                "agent_name": aname,
                "sampled_theta": theta,
                "alpha": s["alpha"],
                "beta": s["beta"],
                "pulls": s["pulls"],
            })

        if forced:
            pick = self._rng.choice(sampled)
            decision_mode = "EXPLORATION"
        else:
            pick = max(sampled, key=lambda x: x["sampled_theta"])
            decision_mode = mode  # SHADOW or LIVE

        # Under-pulled safeguard: if the picked arm has < MIN_PULLS_FOR_LIVE
        # and we're running LIVE, downgrade to SHADOW for this decision to
        # avoid committing to a noisy estimate. SHADOW stays SHADOW.
        if decision_mode == "LIVE" and pick["pulls"] < MIN_PULLS_FOR_LIVE:
            decision_mode = "FALLBACK"

        # In SHADOW / FALLBACK, the real selection is whatever the caller used.
        if decision_mode in ("SHADOW", "FALLBACK") and actual_winner_id:
            selected_id = actual_winner_id
            selected_name = actual_winner_name
        else:
            selected_id = pick["agent_id"]
            selected_name = pick["agent_name"]

        decision_id = str(uuid.uuid4())
        decision = BanditDecision(
            decision_id=decision_id,
            context_bucket=context_bucket,
            selected_agent_id=selected_id,
            selected_agent_name=selected_name,
            bandit_pick_agent_id=pick["agent_id"],
            bandit_pick_agent_name=pick["agent_name"],
            mode=decision_mode,
            candidates=sampled,
            trace_id=trace_id,
        )

        # Persist the decision (fire-and-forget-ish; log on failure)
        try:
            conn = self._conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO bandit_decisions
                      (decision_id, trace_id, session_id, graph_id, node_id,
                       context_bucket, mode, candidate_agents,
                       selected_agent_id, selected_agent_name,
                       bandit_pick_agent_id, bandit_pick_agent_name)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        decision_id, trace_id, session_id, graph_id, node_id,
                        context_bucket, decision_mode, json.dumps(sampled),
                        selected_id, selected_name,
                        pick["agent_id"], pick["agent_name"],
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "Bandit decision persist failed",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )

        logger.info(
            "Bandit decision",
            layer="service",
            trace_id=trace_id,
            decision_id=decision_id,
            mode=decision_mode,
            context_bucket=context_bucket,
            bandit_pick=pick["agent_name"] or pick["agent_id"],
            bandit_theta=round(pick["sampled_theta"], 3),
            selected_agent=selected_name or selected_id,
            candidates=len(sampled),
        )
        return decision

    # --------------------------------------------------------------------
    # Core: record_reward()
    # --------------------------------------------------------------------
    def record_reward(
        self,
        decision_id: str,
        reward: float,
        trace_id: str = "",
    ) -> None:
        """Update the bandit state for the agent that was actually executed.

        Reward is clipped to [0, 1]. The (agent, context) Beta is updated
        via the standard Thompson update:
            alpha += reward
            beta  += (1 - reward)
            pulls += 1
            total_reward += reward

        We update the row for the *actual* executed agent (selected_agent_id),
        not the bandit's pick, because that's the arm we have ground truth on.
        """
        r = max(0.0, min(1.0, float(reward)))
        try:
            conn = self._conn()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT selected_agent_id, selected_agent_name, context_bucket, reward "
                    "FROM bandit_decisions WHERE decision_id=%s",
                    (decision_id,),
                )
                row = cur.fetchone()
                if not row:
                    logger.warning(
                        "Bandit reward: decision_id not found",
                        layer="service",
                        decision_id=decision_id,
                        trace_id=trace_id,
                    )
                    return
                if row.get("reward") is not None:
                    # Already rewarded — idempotent no-op
                    return

                agent_id = row["selected_agent_id"]
                agent_name = row.get("selected_agent_name") or ""
                context_bucket = row["context_bucket"]

                # Upsert bandit_agent_state
                prior_alpha = DEFAULT_ALPHA + PRIOR_MEAN * PRIOR_STRENGTH
                prior_beta = DEFAULT_BETA + (1.0 - PRIOR_MEAN) * PRIOR_STRENGTH
                cur.execute(
                    """
                    INSERT INTO bandit_agent_state
                        (agent_id, agent_name, context_bucket, alpha, beta, pulls, total_reward)
                    VALUES (%s,%s,%s,%s,%s,1,%s)
                    ON DUPLICATE KEY UPDATE
                        alpha        = alpha + %s,
                        beta         = beta  + %s,
                        pulls        = pulls + 1,
                        total_reward = total_reward + %s,
                        agent_name   = VALUES(agent_name)
                    """,
                    (
                        agent_id, agent_name, context_bucket,
                        prior_alpha + r,          # first-insert alpha
                        prior_beta + (1.0 - r),   # first-insert beta
                        r,                        # first-insert total_reward
                        r,                        # update alpha delta
                        1.0 - r,                  # update beta delta
                        r,                        # update total_reward delta
                    ),
                )
                cur.execute(
                    "UPDATE bandit_decisions SET reward=%s, reward_recorded_at=NOW() "
                    "WHERE decision_id=%s",
                    (r, decision_id),
                )
                conn.commit()
                logger.info(
                    "Bandit reward recorded",
                    layer="service",
                    decision_id=decision_id,
                    agent_id=agent_id,
                    context_bucket=context_bucket,
                    reward=r,
                    trace_id=trace_id,
                )
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "Bandit record_reward failed",
                layer="service",
                decision_id=decision_id,
                error=str(exc),
                trace_id=trace_id,
            )
