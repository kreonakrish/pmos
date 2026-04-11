"""Train the shadow learned-quality scorer (1B).

Feature vector (all numeric, 15-dim) — chosen to be cheap to compute at
inference time in pure Python, no sentence-transformers required:

    f01  heuristic_score       — the scoring service's own 0–1 output
    f02  response_len_chars    / 4000     (clipped to [0,1])
    f03  response_word_count   / 800      (clipped to [0,1])
    f04  latency_ms            / 60000    (clipped to [0,1])
    f05  had_tool_calls        — 0/1
    f06  tool_call_count       / 10       (clipped to [0,1])
    f07  n_task_nodes          / 20       (clipped to [0,1])
    f08  context_len_chars     / 1000     (clipped to [0,1], from metadata)
    f09  agent_rolling_avg     — agent's own avg score over its last 30 runs
    f10  markdown_headers_pct  — fraction of lines beginning with '#' or '*'
    f11  contains_numbers      — 0/1
    f12  contains_table        — 0/1 (detects '| ' in response)
    f13  contains_code_block   — 0/1 (detects ``` in response)
    f14  contains_refusal      — 0/1 (regex over "cannot","unable","no data")
    f15  graph_depth           / 10       (clipped to [0,1])

Label:
    y=1 if user gave thumbs-up (rl_feedback_log.feedback_source='USER'
        AND feedback_type='SCORE' AND reward_signal > 0)
    y=0 if user gave thumbs-down
    If not enough real labels, synthetic bootstrap from the last 5000 messages:
        y=1 if message.score >= 0.65, y=0 if message.score < 0.65
    The 0.65 threshold is chosen so roughly 60% of rows land positive,
    matching the 60% baseline prior the operator requested.

Output:
    A pickle file at PMOS_MODEL_DIR/learned_scorer_<version>.pkl containing:
        {
          'version': str,
          'feature_names': [f01,...,f15],
          'weights': [float, ...],
          'bias': float,
          'scaler_mean': [float, ...],
          'scaler_scale': [float, ...],
        }
    and a row in pmos.learned_scorer_models pointing at it.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import mysql.connector

logger = logging.getLogger("pmos.train_learned_scorer")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# env
# ---------------------------------------------------------------------------
def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

_load_env()

MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DB = os.environ.get("MYSQL_DB", "pmos")

# Model artifacts. Defaults to a shared host dir that is mounted into the
# orchestrator container as /app/models (see docker-compose volumes section
# below — if not mounted, the orchestrator will simply skip loading and
# learned_scorer.py will operate with zero predictions).
DEFAULT_MODEL_DIR = Path(__file__).resolve().parent.parent / "infra" / "ml_models"
MODEL_DIR = Path(os.environ.get("PMOS_MODEL_DIR", str(DEFAULT_MODEL_DIR)))
MODEL_DIR.mkdir(parents=True, exist_ok=True)


FEATURE_NAMES = [
    "heuristic_score",
    "response_len_chars_norm",
    "response_word_count_norm",
    "latency_ms_norm",
    "had_tool_calls",
    "tool_call_count_norm",
    "n_task_nodes_norm",
    "context_len_chars_norm",
    "agent_rolling_avg",
    "markdown_headers_pct",
    "contains_numbers",
    "contains_table",
    "contains_code_block",
    "contains_refusal",
    "graph_depth_norm",
]

REFUSAL_RE = re.compile(
    r"(cannot|can't|unable to|no data|not able to|no loans|no records|insufficient)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Feature extraction (same function used at inference time)
# ---------------------------------------------------------------------------
def extract_features(row: Dict[str, Any]) -> List[float]:
    """Return a 15-element feature vector from a message-like dict.

    Expected input keys (all optional — missing ones default to 0):
      content           : str — assistant response text
      heuristic_score   : float in [0,1]
      latency_ms        : int
      tool_call_count   : int
      n_task_nodes      : int
      context_len_chars : int
      agent_rolling_avg : float in [0,1]
      graph_depth       : int
    """
    def clip(x: float, hi: float = 1.0) -> float:
        return max(0.0, min(hi, x))

    content = row.get("content") or ""
    heuristic = float(row.get("heuristic_score") or 0.0)
    latency = float(row.get("latency_ms") or 0.0)
    tcalls = float(row.get("tool_call_count") or 0.0)
    n_nodes = float(row.get("n_task_nodes") or 0.0)
    ctx_len = float(row.get("context_len_chars") or 0.0)
    agent_avg = float(row.get("agent_rolling_avg") or 0.0)
    depth = float(row.get("graph_depth") or 0.0)

    n_chars = len(content)
    n_words = len(content.split()) if content else 0
    n_lines = content.count("\n") + 1 if content else 0
    header_lines = sum(
        1 for ln in content.splitlines() if ln.lstrip().startswith(("#", "*", "-"))
    )
    hdr_pct = (header_lines / n_lines) if n_lines > 0 else 0.0
    has_numbers = 1.0 if re.search(r"\d", content) else 0.0
    has_table = 1.0 if ("| " in content and "---" in content) else 0.0
    has_code = 1.0 if "```" in content else 0.0
    has_refusal = 1.0 if REFUSAL_RE.search(content) else 0.0

    return [
        clip(heuristic),
        clip(n_chars / 4000.0),
        clip(n_words / 800.0),
        clip(latency / 60000.0),
        1.0 if tcalls > 0 else 0.0,
        clip(tcalls / 10.0),
        clip(n_nodes / 20.0),
        clip(ctx_len / 1000.0),
        clip(agent_avg),
        clip(hdr_pct),
        has_numbers,
        has_table,
        has_code,
        has_refusal,
        clip(depth / 10.0),
    ]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def _conn():
    return mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASSWORD, database=MYSQL_DB,
    )


def load_real_labels(limit: int = 10000) -> List[Tuple[List[float], int]]:
    """Pull any real user thumbs-up/down into training data."""
    sql = """
        SELECT
          rl.session_id,
          rl.reward_signal,
          rl.feedback_payload,
          rl.processed_at,
          m.content,
          m.score                           AS heuristic_score,
          m.metadata                        AS metadata_json,
          JSON_EXTRACT(m.metadata,'$.latency_ms')   AS latency_ms,
          JSON_EXTRACT(m.metadata,'$.graph_id')     AS graph_id
        FROM rl_feedback_log rl
        LEFT JOIN messages m
          ON m.conversation_id = rl.session_id AND m.role = 'assistant'
        WHERE rl.feedback_source = 'USER'
          AND rl.feedback_type   = 'SCORE'
          AND rl.reward_signal IS NOT NULL
        ORDER BY rl.processed_at DESC
        LIMIT %s
    """
    out: List[Tuple[List[float], int]] = []
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, (limit,))
        for row in cur.fetchall() or []:
            label = 1 if float(row.get("reward_signal") or 0) > 0 else 0
            feats = extract_features({
                "content": row.get("content"),
                "heuristic_score": row.get("heuristic_score") or 0.0,
                "latency_ms": row.get("latency_ms") or 0,
            })
            out.append((feats, label))
    finally:
        conn.close()
    return out


def load_synthetic_labels(limit: int = 5000, threshold: float = 0.65) -> List[Tuple[List[float], int]]:
    """Bootstrap from historical assistant messages.

    Rows with score >= threshold become positive, below become negative.
    The threshold is tuned so roughly 60% land positive (matches the operator's
    60% baseline prior).
    """
    sql = """
        SELECT m.conversation_id, m.content, m.score AS heuristic_score,
               m.metadata AS metadata_json
        FROM messages m
        WHERE m.role = 'assistant' AND m.score IS NOT NULL
        ORDER BY m.created_at DESC
        LIMIT %s
    """
    out: List[Tuple[List[float], int]] = []
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, (limit,))
        for row in cur.fetchall() or []:
            label = 1 if float(row.get("heuristic_score") or 0.0) >= threshold else 0
            feats = extract_features({
                "content": row.get("content"),
                "heuristic_score": row.get("heuristic_score") or 0.0,
            })
            out.append((feats, label))
    finally:
        conn.close()
    return out


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------
def train(
    real: List[Tuple[List[float], int]],
    synthetic: List[Tuple[List[float], int]],
) -> Dict[str, Any]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import accuracy_score, roc_auc_score

    # Upweight real labels 5x so that even a few human thumbs matter more
    # than the synthetic bootstrap.
    X: List[List[float]] = []
    y: List[int] = []
    weights: List[float] = []
    for feats, label in real:
        X.append(feats); y.append(label); weights.append(5.0)
    for feats, label in synthetic:
        X.append(feats); y.append(label); weights.append(1.0)

    if len(X) < 10:
        raise RuntimeError(f"Too few training samples ({len(X)}) — need >= 10")

    n_positive = sum(y)
    logger.info(
        "Training set: total=%d  real=%d  synthetic=%d  positive=%d (%.1f%%)",
        len(X), len(real), len(synthetic), n_positive, 100 * n_positive / len(X),
    )

    # 80/20 train/val split, stratified
    import numpy as np
    X_arr = np.asarray(X, dtype=float)
    y_arr = np.asarray(y, dtype=int)
    w_arr = np.asarray(weights, dtype=float)

    X_tr, X_val, y_tr, y_val, w_tr, _ = train_test_split(
        X_arr, y_arr, w_arr,
        test_size=0.2, random_state=42,
        stratify=y_arr if min(sum(y_arr), len(y_arr) - sum(y_arr)) >= 2 else None,
    )

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_val_s = scaler.transform(X_val)

    clf = LogisticRegression(
        max_iter=2000, C=1.0, solver="liblinear", class_weight="balanced",
    )
    clf.fit(X_tr_s, y_tr, sample_weight=w_tr)

    train_pred = clf.predict(X_tr_s)
    val_pred = clf.predict(X_val_s)
    val_proba = clf.predict_proba(X_val_s)[:, 1]

    train_acc = float(accuracy_score(y_tr, train_pred))
    val_acc = float(accuracy_score(y_val, val_pred))
    try:
        val_auc = float(roc_auc_score(y_val, val_proba)) if len(set(y_val)) == 2 else None
    except Exception:
        val_auc = None

    logger.info(
        "Trained logreg  train_acc=%.3f  val_acc=%.3f  val_auc=%s",
        train_acc, val_acc, f"{val_auc:.3f}" if val_auc is not None else "n/a",
    )

    return {
        "weights": clf.coef_[0].tolist(),
        "bias": float(clf.intercept_[0]),
        "scaler_mean": scaler.mean_.tolist(),
        "scaler_scale": scaler.scale_.tolist(),
        "feature_names": FEATURE_NAMES,
        "n_samples": len(X),
        "n_positive": n_positive,
        "n_real": len(real),
        "n_synthetic": len(synthetic),
        "train_accuracy": train_acc,
        "val_accuracy": val_acc,
        "val_auc": val_auc,
    }


# ---------------------------------------------------------------------------
# Persist
# ---------------------------------------------------------------------------
def save_model(model: Dict[str, Any], notes: str = "") -> Tuple[str, Path]:
    version = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"learned_scorer_{version}.pkl"
    path = MODEL_DIR / filename

    payload = {
        "version": version,
        "feature_names": model["feature_names"],
        "weights": model["weights"],
        "bias": model["bias"],
        "scaler_mean": model["scaler_mean"],
        "scaler_scale": model["scaler_scale"],
    }
    with path.open("wb") as f:
        pickle.dump(payload, f)
    logger.info("Wrote model to %s", path)

    # Record in MySQL and flip is_active
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE learned_scorer_models SET is_active = FALSE WHERE is_active = TRUE")
        cur.execute(
            """
            INSERT INTO learned_scorer_models
                (model_version, algorithm, feature_names, n_features, n_samples,
                 n_positive, n_synthetic, n_real, train_accuracy, val_accuracy,
                 val_auc, weights_path, notes, is_active)
            VALUES (%s,'logreg',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE)
            """,
            (
                version,
                json.dumps(model["feature_names"]),
                len(model["feature_names"]),
                model["n_samples"],
                model["n_positive"],
                model["n_synthetic"],
                model["n_real"],
                model["train_accuracy"],
                model["val_accuracy"],
                model["val_auc"],
                str(path),
                notes,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return version, path


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic-limit", type=int, default=5000)
    parser.add_argument("--real-limit", type=int, default=10000)
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    logger.info("Loading real user feedback labels ...")
    real = load_real_labels(args.real_limit)
    logger.info("Loaded %d real labels", len(real))

    logger.info("Loading synthetic bootstrap labels ...")
    synthetic = load_synthetic_labels(args.synthetic_limit)
    logger.info("Loaded %d synthetic labels", len(synthetic))

    if len(real) + len(synthetic) < 10:
        logger.warning(
            "Too little data to train (real=%d, synthetic=%d). "
            "Run more conversations first.",
            len(real), len(synthetic),
        )
        return 1

    model = train(real, synthetic)
    version, path = save_model(model, notes=args.notes)

    logger.info("")
    logger.info("=== DONE ===")
    logger.info("  model_version : %s", version)
    logger.info("  path          : %s", path)
    logger.info("  val_accuracy  : %.3f", model["val_accuracy"])
    if model["val_auc"] is not None:
        logger.info("  val_auc       : %.3f", model["val_auc"])
    logger.info("  is_active     : TRUE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
