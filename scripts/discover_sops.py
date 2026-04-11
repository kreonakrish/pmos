"""SOP auto-discovery (2D).

Clusters recent user messages by TF-IDF + DBSCAN, picks dense clusters as
candidate Standard Operating Procedures, and writes PENDING rows to
pmos.sop_proposals. A human reviews and promotes via the ML Insights UI.

Run:
    python scripts/discover_sops.py                    # defaults
    python scripts/discover_sops.py --min-cluster 3 --window-days 60
    python scripts/discover_sops.py --dry-run          # print without writing

Cadence: run weekly via cron / Task Scheduler / k8s CronJob.

The operator confirmed human-in-loop review is required — this script
never writes to Neo4j directly. Promotion happens through the UI, which
flips sop_proposals.status to PROMOTED and creates an SOPNode.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import mysql.connector

logger = logging.getLogger("pmos.discover_sops")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


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


def _conn():
    return mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASSWORD, database=MYSQL_DB,
    )


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_user_messages(window_days: int) -> List[Dict[str, Any]]:
    """Pull user messages from the last N days, joined with the assistant
    response score and agent assignment where available.
    """
    since = datetime.now() - timedelta(days=window_days)
    sql = """
        SELECT
          m.message_id,
          m.conversation_id,
          m.content,
          m.created_at,
          m.trace_id,
          -- best-effort: pair with the next assistant message in the same
          -- conversation to get the score and graph metadata
          (SELECT m2.score FROM messages m2
             WHERE m2.conversation_id = m.conversation_id
               AND m2.role = 'assistant'
               AND m2.created_at >= m.created_at
             ORDER BY m2.created_at ASC LIMIT 1) AS assistant_score,
          (SELECT JSON_EXTRACT(m2.metadata, '$.agent_name') FROM messages m2
             WHERE m2.conversation_id = m.conversation_id
               AND m2.role = 'assistant'
               AND m2.created_at >= m.created_at
             ORDER BY m2.created_at ASC LIMIT 1) AS agent_name
        FROM messages m
        WHERE m.role = 'user'
          AND m.created_at >= %s
          AND m.content IS NOT NULL
          AND CHAR_LENGTH(m.content) >= 15
        ORDER BY m.created_at DESC
        LIMIT 10000
    """
    rows: List[Dict[str, Any]] = []
    conn = _conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, (since,))
        for r in cur.fetchall() or []:
            r["content"] = str(r["content"] or "")
            if r.get("agent_name"):
                # JSON_EXTRACT returns the value with quotes
                an = str(r["agent_name"])
                if an.startswith('"') and an.endswith('"'):
                    an = an[1:-1]
                r["agent_name"] = an
            rows.append(r)
    finally:
        conn.close()
    return rows


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------
def cluster_messages(
    rows: List[Dict[str, Any]],
    eps: float,
    min_samples: int,
) -> Tuple[List[int], List[str], Any]:
    """TF-IDF vectorize and run DBSCAN. Returns (labels, vocab, tfidf_matrix)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import DBSCAN

    texts = [r["content"] for r in rows]
    vec = TfidfVectorizer(
        max_features=2000,
        ngram_range=(1, 2),
        stop_words="english",
        min_df=2,
        sublinear_tf=True,
    )
    X = vec.fit_transform(texts)
    # Cosine distance = 1 - cosine similarity. DBSCAN with metric='cosine'.
    db = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine")
    labels = db.fit_predict(X)
    vocab = vec.get_feature_names_out().tolist()
    return labels.tolist(), vocab, X


def cluster_keywords(
    X: Any,
    indices: List[int],
    vocab: List[str],
    top_k: int = 10,
) -> List[str]:
    """Top TF-IDF terms averaged over the rows in this cluster."""
    import numpy as np
    sub = X[indices]
    mean = sub.mean(axis=0)
    arr = np.asarray(mean).ravel()
    top = arr.argsort()[::-1][:top_k]
    return [vocab[i] for i in top if arr[i] > 0]


# ---------------------------------------------------------------------------
# Proposal building + write
# ---------------------------------------------------------------------------
def build_summary(keywords: List[str], samples: List[str]) -> str:
    """Machine-generated one-liner. No LLM call — just a shape that is
    good enough to be reviewed by a human.
    """
    if not keywords and not samples:
        return "Recurring user request"
    kw_str = ", ".join(keywords[:5]) if keywords else ""
    base = f"Recurring user request pattern"
    if kw_str:
        base += f" about: {kw_str}"
    if samples:
        trimmed = samples[0][:100].replace("\n", " ")
        base += f'. Example: "{trimmed}..."'
    return base


def write_proposals(
    proposals: List[Dict[str, Any]],
    dry_run: bool = False,
) -> int:
    if dry_run or not proposals:
        return 0
    conn = _conn()
    try:
        cur = conn.cursor()
        # Clear old PENDING rows from previous runs to avoid duplicates.
        cur.execute("DELETE FROM sop_proposals WHERE status='PENDING'")
        for p in proposals:
            cur.execute(
                """
                INSERT INTO sop_proposals
                    (proposal_id, cluster_size, avg_score,
                     best_agent_id, best_agent_name,
                     summary, sample_messages, keywords, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'PENDING')
                """,
                (
                    p["proposal_id"], p["cluster_size"], p.get("avg_score"),
                    p.get("best_agent_id"), p.get("best_agent_name"),
                    p["summary"],
                    json.dumps(p["sample_messages"]),
                    json.dumps(p["keywords"]),
                ),
            )
        conn.commit()
        return len(proposals)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--window-days", type=int, default=90,
                   help="look-back window for user messages")
    p.add_argument("--min-cluster", type=int, default=3,
                   help="minimum messages per cluster (DBSCAN min_samples)")
    p.add_argument("--eps", type=float, default=0.55,
                   help="DBSCAN epsilon (cosine distance)")
    p.add_argument("--max-samples", type=int, default=5,
                   help="max example messages per proposal")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    logger.info("Loading user messages in the last %d days ...", args.window_days)
    rows = load_user_messages(args.window_days)
    logger.info("Loaded %d user messages", len(rows))
    if len(rows) < args.min_cluster * 2:
        logger.warning(
            "Not enough messages to cluster (need >= %d). Run more conversations first.",
            args.min_cluster * 2,
        )
        return 0

    logger.info(
        "Clustering with DBSCAN (eps=%.2f, min_samples=%d) ...",
        args.eps, args.min_cluster,
    )
    labels, vocab, X = cluster_messages(rows, eps=args.eps, min_samples=args.min_cluster)

    by_cluster: Dict[int, List[int]] = defaultdict(list)
    for i, lab in enumerate(labels):
        if lab == -1:
            continue  # DBSCAN noise
        by_cluster[lab].append(i)

    logger.info(
        "Found %d clusters (+ %d noise)",
        len(by_cluster),
        sum(1 for l in labels if l == -1),
    )

    proposals: List[Dict[str, Any]] = []
    for cluster_id, member_idxs in sorted(by_cluster.items(), key=lambda t: -len(t[1])):
        members = [rows[i] for i in member_idxs]
        scores = [float(m["assistant_score"]) for m in members if m.get("assistant_score") is not None]
        avg_score = sum(scores) / len(scores) if scores else None

        # Best agent = the one with highest avg score across cluster members
        agent_scores: Dict[str, List[float]] = defaultdict(list)
        for m in members:
            an = m.get("agent_name")
            sc = m.get("assistant_score")
            if an and sc is not None:
                agent_scores[an].append(float(sc))
        best_agent_name = None
        best_avg = -1.0
        for name, sl in agent_scores.items():
            avg = sum(sl) / len(sl)
            if avg > best_avg:
                best_avg = avg
                best_agent_name = name

        keywords = cluster_keywords(X, member_idxs, vocab, top_k=10)
        # Sample the first N messages (deterministic)
        samples = [m["content"][:500] for m in members[: args.max_samples]]
        summary = build_summary(keywords, samples)

        proposals.append({
            "proposal_id": str(uuid.uuid4()),
            "cluster_size": len(members),
            "avg_score": avg_score,
            "best_agent_id": None,  # resolved from name server-side if needed
            "best_agent_name": best_agent_name,
            "summary": summary,
            "sample_messages": samples,
            "keywords": keywords,
        })

    logger.info("Built %d proposals", len(proposals))
    for i, prop in enumerate(proposals[:5]):
        logger.info(
            "  [%d] size=%d avg_score=%s agent=%s keywords=%s",
            i + 1,
            prop["cluster_size"],
            f"{prop['avg_score']:.2f}" if prop.get("avg_score") is not None else "n/a",
            prop.get("best_agent_name") or "-",
            prop["keywords"][:5],
        )

    if args.dry_run:
        logger.info("DRY RUN — not writing to sop_proposals")
        return 0

    written = write_proposals(proposals)
    logger.info("Wrote %d proposals to pmos.sop_proposals (status=PENDING)", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
