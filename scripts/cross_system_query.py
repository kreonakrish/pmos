"""Cross-system query: PMOS Neo4j execution graph + MySQL home-lending data.

Joins data from two completely different stores (Neo4j AuraDB graph of TaskGraphs/
TaskNodes, and MySQL business-domain schemas seeded by business_domains.sql), and
answers questions that require evidence from both.

Run:
    python scripts/cross_system_query.py

Env (loaded from pmos/.env automatically if present):
    NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, NEO4J_DATABASE
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

import mysql.connector
from neo4j import GraphDatabase

# ── env loader ──────────────────────────────────────────────────────────────
def _load_env_file() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

_load_env_file()

NEO4J_URI = os.environ.get("NEO4J_URI", "")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")
NEO4J_DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

MYSQL_HOST = os.environ.get("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("MYSQL_PORT", "3306"))
MYSQL_USER = os.environ.get("MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("MYSQL_PASSWORD", "")


def _print_header(title: str) -> None:
    bar = "=" * 78
    print(f"\n{bar}\n  {title}\n{bar}")


def _print_rows(rows: List[Dict[str, Any]], cols: List[str]) -> None:
    if not rows:
        print("  (no rows)")
        return
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    print("  " + "  ".join(c.ljust(widths[c]) for c in cols))
    print("  " + "  ".join("-" * widths[c] for c in cols))
    for r in rows:
        print("  " + "  ".join(str(r.get(c, "")).ljust(widths[c]) for c in cols))


# ── Neo4j helpers ───────────────────────────────────────────────────────────
def neo4j_query(driver, cypher: str, **params) -> List[Dict[str, Any]]:
    with driver.session(database=NEO4J_DATABASE) as session:
        result = session.run(cypher, **params)
        return [dict(r) for r in result]


# ── MySQL helpers ───────────────────────────────────────────────────────────
def mysql_query(database: str, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASSWORD,
        database=database,
    )
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        conn.close()


# ── Question 1 ──────────────────────────────────────────────────────────────
def q1_recent_pipelines_with_loan_context(driver) -> None:
    """Q1: For the most recent PMOS task graphs, what loans/borrowers are
    referenced in their user requests, and what is the current servicing status
    of those loans?
    """
    _print_header("Q1: Recent PMOS task graphs cross-referenced with loan status")

    graphs = neo4j_query(
        driver,
        """
        MATCH (g:TaskGraph)
        WHERE g.user_request IS NOT NULL
        RETURN g.graph_id AS graph_id,
               g.user_request AS user_request,
               g.status AS status,
               toString(g.created_at) AS created_at
        ORDER BY g.created_at DESC
        LIMIT 25
        """,
    )

    # Pull all loans into memory once.
    loans = mysql_query(
        "pmos_servicing",
        """
        SELECT loan_id, borrower_name, property_address, current_balance,
               status, investor_id
        FROM loans
        """,
    )

    matches: List[Dict[str, Any]] = []
    for g in graphs:
        ur = (g.get("user_request") or "").lower()
        if not ur:
            continue
        for ln in loans:
            loan_id = ln["loan_id"].lower()
            borrower = ln["borrower_name"].lower().split()[0]  # first name
            if loan_id in ur or borrower in ur:
                matches.append({
                    "graph_id": g["graph_id"][:8],
                    "loan_id": ln["loan_id"],
                    "borrower": ln["borrower_name"],
                    "loan_status": ln["status"],
                    "balance": f"${ln['current_balance']:,.0f}",
                    "graph_status": g["status"],
                })

    print(f"  Scanned {len(graphs)} recent task graphs against {len(loans)} loans.")
    if matches:
        _print_rows(matches, ["graph_id", "loan_id", "borrower", "loan_status", "balance", "graph_status"])
    else:
        print("  No task graph user_requests reference servicing loans by id or first name.")
        print("  -> Insight: agents have not yet been routed to query the home-lending data.")


# ── Question 2 ──────────────────────────────────────────────────────────────
def q2_high_risk_loans_full_lifecycle() -> None:
    """Q2: Show the full origination -> servicing trail for HIGH/SEVERE-risk loans:
    where did each loan come from (consumer or correspondent), what marketing
    lead led to it, and what enforcement actions are open today?
    """
    _print_header("Q2: HIGH/SEVERE-risk loans — full origination -> servicing trail")

    risky = mysql_query(
        "pmos_servicing",
        """
        SELECT l.loan_id, l.borrower_name, l.status, l.origination_source,
               l.origination_ref, ra.risk_score, ra.risk_band
        FROM loans l
        JOIN risk_assessments ra ON ra.loan_id = l.loan_id
        WHERE ra.risk_band IN ('HIGH','SEVERE')
        ORDER BY ra.risk_score DESC
        """,
    )

    rows = []
    for r in risky:
        loan_id = r["loan_id"]
        # Open foreclosures
        fc = mysql_query(
            "pmos_servicing",
            "SELECT COUNT(*) AS n FROM foreclosures WHERE loan_id=%s AND status IN ('INITIATED','SOLD','REO')",
            (loan_id,),
        )
        # Bankruptcies
        bk = mysql_query(
            "pmos_servicing",
            "SELECT COUNT(*) AS n FROM bankruptcies WHERE loan_id=%s AND status IN ('FILED','DISCHARGED','CONVERTED')",
            (loan_id,),
        )
        # Origination source detail
        origin_summary = ""
        if r["origination_source"] == "CONSUMER":
            uw = mysql_query(
                "pmos_origination_consumer",
                """
                SELECT a.application_id, a.fico_score, u.dti_ratio, u.ltv_ratio, u.decision
                FROM consumer_applications a
                LEFT JOIN consumer_underwriting u ON u.application_id = a.application_id
                WHERE a.application_id = %s
                """,
                (r["origination_ref"],),
            )
            if uw:
                u = uw[0]
                origin_summary = f"consumer fico={u['fico_score']} dti={u['dti_ratio']} ltv={u['ltv_ratio']} -> {u['decision']}"
        else:  # CORRESPONDENT
            cp = mysql_query(
                "pmos_origination_correspondent",
                """
                SELECT p.purchase_id, p.premium_pct, l.name AS lender, dd.status AS dd_status
                FROM correspondent_purchases p
                JOIN correspondent_lenders l ON l.lender_id = p.lender_id
                LEFT JOIN correspondent_due_diligence dd ON dd.purchase_id = p.purchase_id
                WHERE p.purchase_id = %s
                """,
                (r["origination_ref"],),
            )
            if cp:
                c = cp[0]
                origin_summary = f"correspondent {c['lender']} premium={c['premium_pct']} dd={c['dd_status']}"

        rows.append({
            "loan_id": loan_id,
            "borrower": r["borrower_name"][:22],
            "risk": f"{r['risk_score']} {r['risk_band']}",
            "loan_status": r["status"],
            "origination": origin_summary[:55],
            "fc": fc[0]["n"],
            "bk": bk[0]["n"],
        })

    _print_rows(rows, ["loan_id", "borrower", "risk", "loan_status", "origination", "fc", "bk"])


# ── Question 3 ──────────────────────────────────────────────────────────────
def q3_marketing_to_servicing_funnel() -> None:
    """Q3: For each marketing campaign, what % of its leads ultimately became
    funded loans now in servicing, and what is their aggregate balance?
    """
    _print_header("Q3: Marketing -> Sales -> Origination -> Servicing funnel by campaign")

    leads = mysql_query(
        "pmos_marketing",
        """
        SELECT c.campaign_id, c.name AS campaign, c.channel, l.lead_id, l.email
        FROM marketing_campaigns c
        JOIN marketing_leads l ON l.campaign_id = c.campaign_id
        """,
    )

    sales = mysql_query(
        "pmos_sales",
        "SELECT lead_id AS sales_id, marketing_lead_id, customer_email, status FROM sales_leads",
    )

    apps = mysql_query(
        "pmos_origination_consumer",
        "SELECT application_id, sales_lead_id, email FROM consumer_applications WHERE status='APPROVED'",
    )

    closings = mysql_query(
        "pmos_origination_consumer",
        "SELECT closing_id, application_id, funded_loan_id FROM consumer_closings WHERE status='COMPLETED'",
    )

    loans = {l["loan_id"]: l for l in mysql_query(
        "pmos_servicing", "SELECT loan_id, current_balance, status FROM loans")}

    # Build chains: marketing_lead -> sales_lead -> application -> closing -> loan
    sales_by_mlead = {s["marketing_lead_id"]: s for s in sales if s["marketing_lead_id"]}
    apps_by_slead = {a["sales_lead_id"]: a for a in apps if a["sales_lead_id"]}
    closings_by_app = {c["application_id"]: c for c in closings}

    funnel: Dict[str, Dict[str, Any]] = {}
    for ld in leads:
        cid = ld["campaign_id"]
        f = funnel.setdefault(cid, {
            "campaign": ld["campaign"][:30],
            "channel": ld["channel"],
            "leads": 0, "sales": 0, "apps": 0, "funded": 0,
            "balance": 0.0,
        })
        f["leads"] += 1
        s = sales_by_mlead.get(ld["lead_id"])
        if not s:
            continue
        f["sales"] += 1
        a = apps_by_slead.get(s["sales_id"])
        if not a:
            continue
        f["apps"] += 1
        c = closings_by_app.get(a["application_id"])
        if not c or not c["funded_loan_id"]:
            continue
        ln = loans.get(c["funded_loan_id"])
        if not ln:
            continue
        f["funded"] += 1
        f["balance"] += float(ln["current_balance"])

    rows = []
    for cid, f in sorted(funnel.items()):
        conv = (f["funded"] / f["leads"] * 100) if f["leads"] else 0
        rows.append({
            "campaign": f["campaign"],
            "channel": f["channel"],
            "leads": f["leads"],
            "sales": f["sales"],
            "apps": f["apps"],
            "funded": f["funded"],
            "conv_pct": f"{conv:.0f}%",
            "balance": f"${f['balance']:,.0f}",
        })
    _print_rows(rows, ["campaign", "channel", "leads", "sales", "apps", "funded", "conv_pct", "balance"])


# ── Question 4 ──────────────────────────────────────────────────────────────
def q4_pmos_agents_used_for_lending(driver) -> None:
    """Q4: Which PMOS agents have produced execution events recently, and could
    any of them realistically be the one(s) that should be answering questions
    about loans in DEFAULT/FORECLOSURE?
    """
    _print_header("Q4: PMOS agents (Neo4j) vs. servicing escalation backlog (MySQL)")

    agent_rows = neo4j_query(
        driver,
        """
        MATCH (n:TaskNode)
        WHERE n.assigned_agent_name IS NOT NULL
        RETURN n.assigned_agent_name AS agent,
               count(*) AS task_count,
               avg(n.score) AS avg_score
        ORDER BY task_count DESC
        LIMIT 10
        """,
    )

    backlog = mysql_query(
        "pmos_servicing",
        """
        SELECT status, COUNT(*) AS n, SUM(current_balance) AS upb
        FROM loans
        WHERE status IN ('DELINQUENT','DEFAULT','BANKRUPTCY','FORECLOSURE','REO')
        GROUP BY status
        ORDER BY n DESC
        """,
    )

    print("  Top PMOS agents by task volume (Neo4j TaskNodes):")
    if agent_rows:
        rows = []
        for a in agent_rows:
            avg_s = a.get("avg_score")
            rows.append({
                "agent": str(a.get("agent", ""))[:32],
                "task_count": a.get("task_count", 0),
                "avg_score": f"{avg_s:.2f}" if avg_s is not None else "n/a",
            })
        _print_rows(rows, ["agent", "task_count", "avg_score"])
    else:
        print("  (no TaskNodes with assigned_agent_name yet)")

    print("\n  Servicing escalation backlog (MySQL pmos_servicing.loans):")
    rows = [{
        "status": b["status"],
        "count": b["n"],
        "unpaid_balance": f"${float(b['upb']):,.0f}",
    } for b in backlog]
    _print_rows(rows, ["status", "count", "unpaid_balance"])

    print(
        "\n  Cross-system insight: the PMOS team-routing layer should map any "
        "user question containing 'default', 'foreclosure', 'bankruptcy', or "
        "'REDS' to an agent that has been granted the servicing_db tool "
        "(tool_id a0000006-0000-0000-0000-00000000svc1)."
    )


# ── Question 5 ──────────────────────────────────────────────────────────────
def q5_investor_exposure_to_distress() -> None:
    """Q5: Which investors hold the most distressed UPB right now, and what
    regulatory filings (REDS) have already gone out on those loans?
    """
    _print_header("Q5: Investor exposure to distressed loans + open REDS filings")

    rows = mysql_query(
        "pmos_servicing",
        """
        SELECT i.investor_id, i.name AS investor, i.investor_type,
               COUNT(l.loan_id) AS loans,
               SUM(CASE WHEN l.status IN ('DELINQUENT','DEFAULT','BANKRUPTCY','FORECLOSURE','REO')
                        THEN l.current_balance ELSE 0 END) AS distressed_upb,
               SUM(l.current_balance) AS total_upb
        FROM investors i
        LEFT JOIN loans l ON l.investor_id = i.investor_id
        GROUP BY i.investor_id, i.name, i.investor_type
        HAVING loans > 0
        ORDER BY distressed_upb DESC
        """,
    )

    out = []
    for r in rows:
        loan_ids = mysql_query(
            "pmos_servicing",
            "SELECT loan_id FROM loans WHERE investor_id=%s",
            (r["investor_id"],),
        )
        ids = [x["loan_id"] for x in loan_ids]
        if ids:
            placeholders = ",".join(["%s"] * len(ids))
            reds = mysql_query(
                "pmos_servicing",
                f"SELECT COUNT(*) AS n FROM reds_filings WHERE loan_id IN ({placeholders})",
                tuple(ids),
            )
            reds_n = reds[0]["n"]
        else:
            reds_n = 0
        out.append({
            "investor": r["investor"][:28],
            "type": r["investor_type"],
            "loans": r["loans"],
            "total_upb": f"${float(r['total_upb'] or 0):,.0f}",
            "distressed_upb": f"${float(r['distressed_upb'] or 0):,.0f}",
            "reds_filings": reds_n,
        })
    _print_rows(out, ["investor", "type", "loans", "total_upb", "distressed_upb", "reds_filings"])


# ── main ────────────────────────────────────────────────────────────────────
def main() -> int:
    print("PMOS cross-system query - Neo4j (TaskGraph) JOIN MySQL (home lending)")
    print(f"  Neo4j  : {NEO4J_URI}")
    print(f"  MySQL  : {MYSQL_USER}@{MYSQL_HOST}:{MYSQL_PORT}")

    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
    except Exception as exc:
        print(f"\n[warn] Neo4j connect failed: {exc}", file=sys.stderr)
        print("[warn] Q1 / Q4 will run with empty Neo4j results.", file=sys.stderr)
        driver = None

    try:
        if driver:
            q1_recent_pipelines_with_loan_context(driver)
        else:
            _print_header("Q1: skipped (no Neo4j)")

        q2_high_risk_loans_full_lifecycle()
        q3_marketing_to_servicing_funnel()

        if driver:
            q4_pmos_agents_used_for_lending(driver)
        else:
            _print_header("Q4: skipped (no Neo4j)")

        q5_investor_exposure_to_distress()
    finally:
        if driver:
            driver.close()

    print("\nDone.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
