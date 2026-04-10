"""
PMOS Validation Suite -- Fixture generator.

Generates sample documents used by ingestion and RAG validation suites.
Call ``generate_fixtures()`` before running suites.
"""
from __future__ import annotations

import csv
import os
import random
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _ensure_dir() -> None:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# sample_document.txt
# ---------------------------------------------------------------------------

_TXT_CONTENT = """\
PMOS -- Perpetual Multi-Agent Orchestration System

The living graph is the central data structure of PMOS.  Every intermediate LLM
response that spawns sub-questions becomes a new TaskNode in Neo4j before
execution proceeds.  There are no static DAGs -- the graph is always live.

Neo4j stores TaskNode, ExecutionEvent, SOPNode, and AgentCapabilityNode entities
connected by relationships such as SPAWNED_BY, ASSIGNED_TO, FOLLOWS_SOP,
BELONGS_TO, and UPDATED_FROM.

MySQL handles relational data: agents, tools, teams, scoring weights, RL feedback
logs, score history, memory tables, capability registry, and execution graph logs.
Each service owns its own set of tables and never writes to another service's
tables.

Redis provides pub/sub and stream-based communication between services.  Key
streams include orchestrator:tasks, memory:writes, scoring:feedback,
events:telemetry, events:tool_health, events:capability_added, and
events:documents.

Qdrant (or FAISS / Pinecone / Weaviate via config) powers the vector search
backend for the RAG pipeline.  The RAG service performs parallel retrieval from
up to four sources, then re-ranks candidates with a cross-encoder model.

Scoring uses six weighted factors: Relevance (R), Accuracy (Acc), Tool Success
(P), Latency Penalty (Lat), Memory Utilization (Conf), and Validation Pass
(Know).  Weights are adapted via reinforcement learning -- the system never uses
hard-coded thresholds.

Adaptive bands are computed from rolling execution history using:
    band = rolling_mean(last_N) +/- (rolling_std(last_N) * sensitivity_factor)
with minimum width enforcement and absolute floor/ceiling.

The memory subsystem has four tiers:
  1. SHORT_TERM -- Redis hash with TTL
  2. LONG_TERM  -- MySQL + per-agent FAISS shard
  3. REASONING  -- MySQL JSON column, updated via distillation
  4. EPISODIC   -- MySQL table with full episode blobs + embeddings

Every system prompt is assembled at runtime from all four memory tiers -- no
prompt literals appear in source code.

The meta-assembly service detects capability gaps and generates new tool, skill,
or agent specifications using an LLM.  Generated code runs in an isolated
subprocess with timeout and resource limits.  Safety checks prohibit system
calls, file writes outside sandbox, and network calls to non-whitelisted hosts.
"""


def generate_txt() -> Path:
    path = FIXTURES_DIR / "sample_document.txt"
    path.write_text(_TXT_CONTENT, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# sample_document.csv
# ---------------------------------------------------------------------------

_PRODUCTS = [
    ("Widget Alpha", "Electronics"),
    ("Widget Beta", "Electronics"),
    ("Gadget One", "Gadgets"),
    ("Gadget Two", "Gadgets"),
    ("Sensor Pro", "IoT"),
    ("Sensor Lite", "IoT"),
    ("Board X1", "Hardware"),
    ("Board X2", "Hardware"),
    ("Cable Ultra", "Accessories"),
    ("Cable Basic", "Accessories"),
    ("Display 4K", "Displays"),
    ("Display 8K", "Displays"),
    ("Battery Pack", "Power"),
    ("Solar Panel", "Power"),
    ("Router Mesh", "Networking"),
    ("Switch 48P", "Networking"),
    ("Drone Mini", "Robotics"),
    ("Drone Max", "Robotics"),
    ("Cam 360", "Security"),
    ("Lock Smart", "Security"),
]


def generate_csv() -> Path:
    path = FIXTURES_DIR / "sample_document.csv"
    random.seed(42)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "product_name", "category", "revenue", "units_sold", "rating"])
        for idx, (name, cat) in enumerate(_PRODUCTS, start=1):
            revenue = round(random.uniform(1000, 500000), 2)
            units = random.randint(10, 50000)
            rating = round(random.uniform(1.0, 5.0), 1)
            writer.writerow([idx, name, cat, revenue, units, rating])
    return path


# ---------------------------------------------------------------------------
# sample_document.pdf
# ---------------------------------------------------------------------------

def generate_pdf() -> Path | None:
    path = FIXTURES_DIR / "sample_document.pdf"
    try:
        from fpdf import FPDF  # fpdf2

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        for line in _TXT_CONTENT.strip().splitlines():
            pdf.cell(0, 5, line, new_x="LMARGIN", new_y="NEXT")
        pdf.output(str(path))
        return path
    except ImportError:
        # fpdf2 not installed -- write a minimal dummy PDF so the file exists
        # but mark PDF-dependent tests as SKIP at runtime.
        path.write_bytes(
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
            b"xref\n0 4\ntrailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
        )
        return None  # signal that PDF generation was not fully available


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_fixtures() -> None:
    _ensure_dir()
    txt = generate_txt()
    print(f"  [fixture] {txt}")
    csv_path = generate_csv()
    print(f"  [fixture] {csv_path}")
    pdf = generate_pdf()
    if pdf:
        print(f"  [fixture] {FIXTURES_DIR / 'sample_document.pdf'} (fpdf2)")
    else:
        print(f"  [fixture] {FIXTURES_DIR / 'sample_document.pdf'} (dummy -- fpdf2 not installed)")


if __name__ == "__main__":
    generate_fixtures()
