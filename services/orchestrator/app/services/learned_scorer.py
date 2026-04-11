"""Shadow learned-quality scorer (1B) — inference side.

Loads a logistic-regression model pickled by scripts/train_learned_scorer.py
and runs predictions in pure Python. No numpy / no sklearn — only stdlib +
mysql.connector (already in the orchestrator container).

Used in shadow mode: on every scoring call the pipeline also asks this module
for a prediction and records it to `learned_scorer_predictions`. The
prediction does NOT yet influence the live score — w7_learned_quality in
scoring_weights is kept at 0.0 until the operator decides to flip it.

Model file format (produced by train_learned_scorer.py):
    {
      'version': str,
      'feature_names': [str, ...],
      'weights': [float, ...],
      'bias': float,
      'scaler_mean': [float, ...],
      'scaler_scale': [float, ...],
    }
"""

from __future__ import annotations

import json
import math
import os
import pickle
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import mysql.connector

from app.config import settings
from app.utils.logger import logger

# Container path where docker-compose mounts the host infra/ml_models dir.
MODEL_DIR = Path(os.environ.get("PMOS_MODEL_DIR", "/app/models"))

REFUSAL_RE = re.compile(
    r"(cannot|can't|unable to|no data|not able to|no loans|no records|insufficient)",
    re.IGNORECASE,
)


def _clip(x: float, hi: float = 1.0) -> float:
    return max(0.0, min(hi, x))


def extract_features(ctx: Dict[str, Any]) -> Dict[str, float]:
    """Same feature contract as scripts/train_learned_scorer.py — must stay in sync.

    Returned dict is ordered by insertion order but the LearnedScorer.predict()
    method re-orders by the model's feature_names before doing the dot product.
    """
    content = ctx.get("content") or ""
    heuristic = float(ctx.get("heuristic_score") or 0.0)
    latency = float(ctx.get("latency_ms") or 0.0)
    tcalls = float(ctx.get("tool_call_count") or 0.0)
    n_nodes = float(ctx.get("n_task_nodes") or 0.0)
    ctx_len = float(ctx.get("context_len_chars") or 0.0)
    agent_avg = float(ctx.get("agent_rolling_avg") or 0.0)
    depth = float(ctx.get("graph_depth") or 0.0)

    n_chars = len(content)
    n_words = len(content.split()) if content else 0
    n_lines = (content.count("\n") + 1) if content else 0
    header_lines = sum(
        1 for ln in content.splitlines() if ln.lstrip().startswith(("#", "*", "-"))
    )
    hdr_pct = (header_lines / n_lines) if n_lines > 0 else 0.0
    has_numbers = 1.0 if re.search(r"\d", content) else 0.0
    has_table = 1.0 if ("| " in content and "---" in content) else 0.0
    has_code = 1.0 if "```" in content else 0.0
    has_refusal = 1.0 if REFUSAL_RE.search(content) else 0.0

    return {
        "heuristic_score": _clip(heuristic),
        "response_len_chars_norm": _clip(n_chars / 4000.0),
        "response_word_count_norm": _clip(n_words / 800.0),
        "latency_ms_norm": _clip(latency / 60000.0),
        "had_tool_calls": 1.0 if tcalls > 0 else 0.0,
        "tool_call_count_norm": _clip(tcalls / 10.0),
        "n_task_nodes_norm": _clip(n_nodes / 20.0),
        "context_len_chars_norm": _clip(ctx_len / 1000.0),
        "agent_rolling_avg": _clip(agent_avg),
        "markdown_headers_pct": _clip(hdr_pct),
        "contains_numbers": has_numbers,
        "contains_table": has_table,
        "contains_code_block": has_code,
        "contains_refusal": has_refusal,
        "graph_depth_norm": _clip(depth / 10.0),
    }


class LearnedScorer:
    """Thread-safe shadow-mode inference wrapper."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._version: Optional[str] = None
        self._feature_names: List[str] = []
        self._weights: List[float] = []
        self._bias: float = 0.0
        self._scaler_mean: List[float] = []
        self._scaler_scale: List[float] = []
        self._loaded = False

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------
    def _conn(self):
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_db,
            connection_timeout=5,
        )

    def load_active(self) -> bool:
        """Load the currently active model from disk.

        Finds the row with is_active=TRUE in learned_scorer_models and loads
        its weights_path. If the file is missing (e.g. volume not mounted),
        falls back to the newest .pkl in MODEL_DIR.
        """
        try:
            conn = self._conn()
            try:
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    "SELECT model_version, weights_path FROM learned_scorer_models "
                    "WHERE is_active=TRUE ORDER BY created_at DESC LIMIT 1"
                )
                row = cur.fetchone()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning("LearnedScorer: MySQL lookup failed", layer="service", error=str(exc))
            row = None

        candidate_paths: List[Path] = []
        if row:
            host_path = row.get("weights_path") or ""
            # Translate host path -> container path. The training script writes
            # the absolute host path into MySQL; inside the container we need
            # to look up the same filename under /app/models.
            basename = Path(host_path).name
            candidate_paths.append(MODEL_DIR / basename)
            candidate_paths.append(Path(host_path))

        # Fallback: newest pickle in MODEL_DIR
        if MODEL_DIR.exists():
            pkls = sorted(MODEL_DIR.glob("learned_scorer_*.pkl"), reverse=True)
            candidate_paths.extend(pkls)

        for p in candidate_paths:
            if not p.is_file():
                continue
            try:
                with p.open("rb") as f:
                    payload = pickle.load(f)
                with self._lock:
                    self._version = payload.get("version", "")
                    self._feature_names = list(payload["feature_names"])
                    self._weights = [float(x) for x in payload["weights"]]
                    self._bias = float(payload.get("bias", 0.0))
                    self._scaler_mean = [float(x) for x in payload.get("scaler_mean", [0.0] * len(self._weights))]
                    self._scaler_scale = [float(x) for x in payload.get("scaler_scale", [1.0] * len(self._weights))]
                    self._loaded = True
                logger.info(
                    "LearnedScorer model loaded",
                    layer="service",
                    version=self._version,
                    path=str(p),
                    n_features=len(self._feature_names),
                )
                return True
            except Exception as exc:
                logger.warning(
                    "LearnedScorer: failed to load candidate",
                    layer="service",
                    path=str(p),
                    error=str(exc),
                )
        logger.info(
            "LearnedScorer: no model available; shadow predictions disabled",
            layer="service",
            model_dir=str(MODEL_DIR),
        )
        return False

    def is_loaded(self) -> bool:
        return self._loaded

    @property
    def version(self) -> str:
        return self._version or ""

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def _predict_proba(self, features: Dict[str, float]) -> float:
        if not self._loaded:
            return 0.0
        x = [float(features.get(name, 0.0)) for name in self._feature_names]
        # Standardize
        z = [
            (x[i] - self._scaler_mean[i]) / (self._scaler_scale[i] or 1.0)
            for i in range(len(x))
        ]
        # Linear combination
        s = self._bias
        for i in range(len(z)):
            s += z[i] * self._weights[i]
        # Sigmoid
        try:
            return 1.0 / (1.0 + math.exp(-s))
        except OverflowError:
            return 1.0 if s > 0 else 0.0

    def predict_and_log(
        self,
        ctx: Dict[str, Any],
        trace_id: str = "",
        session_id: str = "",
        graph_id: str = "",
        node_id: str = "",
        agent_id: str = "",
        agent_name: str = "",
        heuristic_score: Optional[float] = None,
    ) -> Optional[float]:
        """Compute a shadow prediction and log it to learned_scorer_predictions.

        Non-blocking on failure — never raises into the pipeline hot path.
        Returns the prediction in [0, 1] or None if no model is loaded.
        """
        if not self._loaded:
            return None
        try:
            features = extract_features({**ctx, "heuristic_score": heuristic_score or ctx.get("heuristic_score")})
            score = self._predict_proba(features)
        except Exception as exc:
            logger.warning(
                "LearnedScorer: feature extraction failed",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )
            return None

        # Persist (fire-and-log on failure)
        try:
            prediction_id = str(uuid.uuid4())
            conn = self._conn()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO learned_scorer_predictions
                        (prediction_id, model_version, trace_id, session_id,
                         graph_id, node_id, agent_id, agent_name,
                         heuristic_score, learned_score, features)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        prediction_id, self._version, trace_id, session_id,
                        graph_id, node_id, agent_id, agent_name,
                        heuristic_score, float(score),
                        json.dumps(features),
                    ),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logger.warning(
                "LearnedScorer: persist failed",
                layer="service",
                error=str(exc),
                trace_id=trace_id,
            )
        return float(score)
