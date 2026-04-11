"""PMOS Node2Vec batch job (2C).

Fetches the TaskGraph from Neo4j, computes Node2Vec embeddings over TaskNodes
and their structural edges (DEPENDS_ON, SPAWNED_BY, EXECUTED_BY), and writes
one 128-dim embedding per node into pmos.task_node_embeddings.

Run:
    python scripts/compute_node2vec.py            # full refresh
    python scripts/compute_node2vec.py --dim 64   # smaller dim for sparse graphs
    python scripts/compute_node2vec.py --walks 20 --length 80
    python scripts/compute_node2vec.py --algorithm spectral   # fallback: no node2vec pkg

Schedule (daily):
    0 3 * * *  cd /path/to/pmos && python scripts/compute_node2vec.py

The embeddings produced by this script become features for:
  - 1B Learned quality scorer (XGBoost input)
  - 1A Contextual bandit (optional context enrichment)
  - Future GNN-based scoring
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import mysql.connector
from neo4j import GraphDatabase

logger = logging.getLogger("pmos.compute_node2vec")
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

NEO4J_URI = os.environ.get("NEO4J_URI", "")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")
MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")
MYSQL_DB = os.environ.get("MYSQL_DB", "pmos")


# ---------------------------------------------------------------------------
# fetch graph from Neo4j
# ---------------------------------------------------------------------------
def fetch_graph() -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
    """Return (nodes, edges). Nodes carry metadata, edges are (from_id, to_id)."""
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    nodes: List[Dict[str, Any]] = []
    edges: List[Tuple[str, str]] = []
    try:
        with driver.session(database=NEO4J_DATABASE) as session:
            logger.info("Fetching TaskNodes from Neo4j ...")
            result = session.run(
                """
                MATCH (n:TaskNode)
                RETURN n.node_id AS node_id,
                       n.graph_id AS graph_id,
                       n.node_type AS node_type
                """
            )
            for record in result:
                node_id = record.get("node_id")
                if not node_id:
                    continue
                nodes.append({
                    "node_id": node_id,
                    "graph_id": record.get("graph_id"),
                    "node_type": record.get("node_type"),
                })

            logger.info("Fetching TaskNode edges from Neo4j ...")
            result = session.run(
                """
                MATCH (a:TaskNode)-[r]->(b:TaskNode)
                WHERE type(r) IN ['DEPENDS_ON','SPAWNED_BY','EXECUTED_BY','PART_OF']
                RETURN a.node_id AS from_id, b.node_id AS to_id, type(r) AS rel
                """
            )
            for record in result:
                fid = record.get("from_id")
                tid = record.get("to_id")
                if fid and tid:
                    edges.append((fid, tid))
    finally:
        driver.close()
    logger.info("Pulled %d nodes and %d edges from Neo4j", len(nodes), len(edges))
    return nodes, edges


# ---------------------------------------------------------------------------
# embedding algorithms
# ---------------------------------------------------------------------------
def compute_node2vec(
    nodes: List[Dict[str, Any]],
    edges: List[Tuple[str, str]],
    dim: int,
    walks: int,
    length: int,
    workers: int,
) -> Dict[str, np.ndarray]:
    """True Node2Vec via the `node2vec` package."""
    try:
        import networkx as nx
        from node2vec import Node2Vec
    except ImportError:
        logger.warning(
            "node2vec / networkx not installed — falling back to spectral embedding"
        )
        return compute_spectral(nodes, edges, dim)

    if not nodes or not edges:
        logger.warning("Graph is empty — no embeddings to compute")
        return {}

    logger.info("Building networkx graph ...")
    G = nx.DiGraph()
    node_ids = {n["node_id"] for n in nodes}
    for nid in node_ids:
        G.add_node(nid)
    for fid, tid in edges:
        if fid in node_ids and tid in node_ids:
            G.add_edge(fid, tid)

    # Drop isolated nodes for the walker — they get zero-vector placeholders
    isolated = [n for n in G.nodes if G.degree(n) == 0]
    if isolated:
        logger.info("Skipping %d isolated nodes in walker", len(isolated))

    live_graph = G.copy()
    live_graph.remove_nodes_from(isolated)

    if live_graph.number_of_nodes() == 0:
        logger.warning("Graph has no connected nodes — returning zeros for all")
        return {nid: np.zeros(dim, dtype=np.float32) for nid in node_ids}

    logger.info(
        "Running Node2Vec: dim=%d walks=%d length=%d on %d nodes / %d edges ...",
        dim, walks, length, live_graph.number_of_nodes(), live_graph.number_of_edges(),
    )
    start = time.time()
    n2v = Node2Vec(
        live_graph,
        dimensions=dim,
        walk_length=length,
        num_walks=walks,
        workers=workers,
        quiet=True,
    )
    # gensim Word2Vec under the hood
    model = n2v.fit(window=10, min_count=1, batch_words=4, epochs=5, sg=1)
    logger.info("Node2Vec fit complete in %.1fs", time.time() - start)

    embeddings: Dict[str, np.ndarray] = {}
    for nid in node_ids:
        if nid in model.wv:
            embeddings[nid] = np.asarray(model.wv[nid], dtype=np.float32)
        else:
            embeddings[nid] = np.zeros(dim, dtype=np.float32)
    return embeddings


def compute_spectral(
    nodes: List[Dict[str, Any]],
    edges: List[Tuple[str, str]],
    dim: int,
) -> Dict[str, np.ndarray]:
    """Dependency-free fallback: Laplacian eigenmaps via pure numpy.

    Produces structure-aware embeddings from the bottom-k eigenvectors of the
    normalized Laplacian. Deterministic, fast for graphs up to ~10k nodes.
    """
    node_ids = [n["node_id"] for n in nodes]
    idx = {nid: i for i, nid in enumerate(node_ids)}
    N = len(node_ids)
    if N == 0:
        return {}

    logger.info("Building adjacency matrix (N=%d) ...", N)
    A = np.zeros((N, N), dtype=np.float32)
    for fid, tid in edges:
        if fid in idx and tid in idx:
            i, j = idx[fid], idx[tid]
            A[i, j] = 1.0
            A[j, i] = 1.0  # symmetrize

    deg = A.sum(axis=1)
    deg[deg == 0] = 1.0
    d_inv_sqrt = 1.0 / np.sqrt(deg)
    # normalized Laplacian: L = I - D^-1/2 A D^-1/2
    D_inv_sqrt = np.diag(d_inv_sqrt)
    L = np.eye(N, dtype=np.float32) - D_inv_sqrt @ A @ D_inv_sqrt

    logger.info("Computing bottom-%d eigenvectors ...", dim + 1)
    # eigh returns in ascending order; drop the trivial first eigenvector (all 1/sqrt(N))
    vals, vecs = np.linalg.eigh(L)
    k = min(dim, N - 1)
    embed_matrix = vecs[:, 1 : 1 + k]  # shape (N, k)
    # Pad to `dim` if the graph is smaller than the requested dimension
    if k < dim:
        pad = np.zeros((N, dim - k), dtype=np.float32)
        embed_matrix = np.concatenate([embed_matrix, pad], axis=1)

    return {nid: embed_matrix[i].astype(np.float32) for nid, i in idx.items()}


# ---------------------------------------------------------------------------
# write to MySQL
# ---------------------------------------------------------------------------
def write_embeddings(
    nodes: List[Dict[str, Any]],
    embeddings: Dict[str, np.ndarray],
    algorithm: str,
    dim: int,
) -> int:
    if not embeddings:
        logger.warning("No embeddings to write")
        return 0

    node_by_id = {n["node_id"]: n for n in nodes}
    conn = mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASSWORD, database=MYSQL_DB,
    )
    try:
        cur = conn.cursor()
        rows = []
        for nid, vec in embeddings.items():
            meta = node_by_id.get(nid, {})
            rows.append((
                nid,
                meta.get("graph_id"),
                meta.get("node_type"),
                dim,
                algorithm,
                json.dumps([float(x) for x in vec]),
            ))
        cur.executemany(
            """
            INSERT INTO task_node_embeddings
                (node_id, graph_id, node_type, dim, algorithm, embedding)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                graph_id=VALUES(graph_id),
                node_type=VALUES(node_type),
                dim=VALUES(dim),
                algorithm=VALUES(algorithm),
                embedding=VALUES(embedding),
                computed_at=CURRENT_TIMESTAMP
            """,
            rows,
        )
        conn.commit()
        written = cur.rowcount
        logger.info("Wrote %d embedding rows (affected=%d)", len(rows), written)
        return len(rows)
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main() -> int:
    parser = argparse.ArgumentParser(description="Compute PMOS TaskNode embeddings")
    parser.add_argument("--dim", type=int, default=128, help="embedding dimension")
    parser.add_argument("--walks", type=int, default=10, help="num walks per node")
    parser.add_argument("--length", type=int, default=40, help="walk length")
    parser.add_argument("--workers", type=int, default=1, help="parallel walk workers")
    parser.add_argument(
        "--algorithm", choices=["node2vec", "spectral"], default="node2vec",
        help="embedding algorithm (spectral is dependency-free fallback)",
    )
    args = parser.parse_args()

    start = time.time()
    nodes, edges = fetch_graph()
    if not nodes:
        logger.warning("No TaskNodes in Neo4j — nothing to embed")
        return 0

    if args.algorithm == "node2vec":
        try:
            embeddings = compute_node2vec(
                nodes, edges,
                dim=args.dim, walks=args.walks, length=args.length,
                workers=args.workers,
            )
            algo_used = "node2vec"
        except Exception as exc:
            logger.error("Node2Vec failed (%s) — falling back to spectral", exc)
            embeddings = compute_spectral(nodes, edges, dim=args.dim)
            algo_used = "spectral"
    else:
        embeddings = compute_spectral(nodes, edges, dim=args.dim)
        algo_used = "spectral"

    write_embeddings(nodes, embeddings, algorithm=algo_used, dim=args.dim)
    logger.info("Done in %.1fs (algorithm=%s)", time.time() - start, algo_used)
    return 0


if __name__ == "__main__":
    sys.exit(main())
