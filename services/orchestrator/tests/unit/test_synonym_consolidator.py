"""Unit tests for Phase F5 — SynonymConsolidator + review-merge endpoint.

Covers:
  * test_clusters_serialized_idempotent — same cluster proposed twice doesn't dupe.
  * test_llm_failure_skips_silently — mocked LLM throws; no exception; no rows.
  * test_review_supersedes_non_canonical — confirm-review fires the supersede + canonical
    create pattern in Neo4j.

We mock the Neo4j adapter and the MySQL connection. Real Cypher is exercised
in the integration suite.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.crawler.synonym_consolidator import (
    SynonymConsolidator,
    _BARecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, store: Dict[str, Any]):
        self._store = store
        self._last_query: str = ""
        self._last_params: tuple = ()
        self._result: List[Any] = []

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._last_query = sql
        self._last_params = params
        if "SELECT proposal_id" in sql:
            # idempotency lookup — return any row whose stored fingerprint matches
            fingerprint = params[-1]
            for row in self._store["rows"]:
                if row["status"] in ("PROPOSED", "IN_REVIEW", "CONFIRMED") and \
                        row["members_json"] == fingerprint:
                    self._result = [(row["proposal_id"],)]
                    return
            self._result = []
        elif "INSERT INTO synonym_proposals" in sql:
            (
                proposal_id, kind, domain, members_json, member_columns_json,
                suggested_attr, suggested_col, rationale, confidence,
            ) = params
            self._store["rows"].append({
                "proposal_id": proposal_id,
                "kind": kind,
                "domain": domain,
                "members_json": members_json,
                "member_columns_json": member_columns_json,
                "suggested_canonical_attr": suggested_attr,
                "suggested_canonical_column": suggested_col,
                "rationale": rationale,
                "confidence": confidence,
                "status": "PROPOSED",
            })
            self._result = []

    def fetchone(self):
        return self._result[0] if self._result else None

    def fetchall(self):
        return list(self._result)


class _FakeConn:
    def __init__(self, store: Dict[str, Any]):
        self._store = store

    def cursor(self, *args, **kwargs):
        # dictionary=True path is unused by the consolidator (it uses tuple cursors).
        return _FakeCursor(self._store)

    def commit(self):
        pass

    def close(self):
        pass


def _make_neo4j_with_bas(records: List[_BARecord]):
    """Build an AsyncMock Neo4jAdapter whose run_query returns the given BA records."""
    neo4j = AsyncMock()

    async def run_query(cypher: str, params=None, trace_id: str = ""):
        # The consolidator's only Cypher call returns the BA list.
        return [
            {
                "fq_name": r.fq_name,
                "name": r.name,
                "domain": r.domain,
                "entity": r.entity,
                "columns": r.columns,
            }
            for r in records
        ]

    neo4j.run_query = AsyncMock(side_effect=run_query)
    return neo4j


# ---------------------------------------------------------------------------
# 1. Idempotency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clusters_serialized_idempotent(monkeypatch):
    """Running the consolidator twice with the same LLM output produces ONE row."""
    bas = [
        _BARecord(
            fq_name="Origination.LoanApplication.borrower_annual_income",
            name="borrower_annual_income",
            domain="Origination",
            entity="LoanApplication",
            columns=[{
                "column_fq_name": "src1::orig.app.borrower_income",
                "column_name": "borrower_income",
                "data_type": "DECIMAL",
                "sample_values": ["50000", "60000"],
                "asset_fq_name": "src1::orig.app",
                "source_name": "src1",
                "source_uri": "mysql://src1",
                "mapping_status": "AUTO_ACCEPTED",
            }],
        ),
        _BARecord(
            fq_name="Origination.CorrespondentPurchase.annual_household_income",
            name="annual_household_income",
            domain="Origination",
            entity="CorrespondentPurchase",
            columns=[{
                "column_fq_name": "src1::orig.cp.household_income",
                "column_name": "household_income",
                "data_type": "DECIMAL",
                "sample_values": ["55000"],
                "asset_fq_name": "src1::orig.cp",
                "source_name": "src1",
                "source_uri": "mysql://src1",
                "mapping_status": "AUTO_ACCEPTED",
            }],
        ),
    ]
    neo4j = _make_neo4j_with_bas(bas)

    llm = AsyncMock()
    llm.complete = AsyncMock(return_value=json.dumps({
        "clusters": [{
            "kind": "SYNONYM",
            "members": [
                "Origination.LoanApplication.borrower_annual_income",
                "Origination.CorrespondentPurchase.annual_household_income",
            ],
            "suggested_canonical_attr": "borrower_annual_income",
            "suggested_canonical_column": "src1::orig.app.borrower_income",
            "rationale": "both encode borrower's yearly income",
            "confidence": 0.9,
        }]
    }))

    store: Dict[str, Any] = {"rows": []}
    consolidator = SynonymConsolidator()
    monkeypatch.setattr(consolidator, "_mysql", lambda: _FakeConn(store))

    # First run — inserts.
    s1 = await consolidator.run(neo4j=neo4j, llm=llm, domain="Origination", trace_id="t-1")
    # Second run — must dedupe.
    s2 = await consolidator.run(neo4j=neo4j, llm=llm, domain="Origination", trace_id="t-2")

    assert s1["clusters_proposed"] == 1
    assert s1["clusters_skipped_dup"] == 0
    assert s2["clusters_proposed"] == 0
    assert s2["clusters_skipped_dup"] == 1
    assert len(store["rows"]) == 1, "exactly one synonym_proposals row across both runs"

    # The stored members_json is the sorted fingerprint, so order in the LLM
    # response cannot create a duplicate.
    inserted = store["rows"][0]
    fp = json.loads(inserted["members_json"])
    assert fp == sorted([
        "Origination.LoanApplication.borrower_annual_income",
        "Origination.CorrespondentPurchase.annual_household_income",
    ])


# ---------------------------------------------------------------------------
# 2. LLM failure tolerance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_failure_skips_silently(monkeypatch):
    """If the LLM raises, the consolidator must not raise and not insert anything."""
    bas = [
        _BARecord(
            fq_name="Servicing.Loan.balance",
            name="balance",
            domain="Servicing",
            entity="Loan",
            columns=[],
        ),
        _BARecord(
            fq_name="Servicing.Loan.current_balance",
            name="current_balance",
            domain="Servicing",
            entity="Loan",
            columns=[],
        ),
    ]
    neo4j = _make_neo4j_with_bas(bas)

    llm = AsyncMock()
    llm.complete = AsyncMock(side_effect=RuntimeError("boom"))

    store: Dict[str, Any] = {"rows": []}
    consolidator = SynonymConsolidator()
    monkeypatch.setattr(consolidator, "_mysql", lambda: _FakeConn(store))

    summary = await consolidator.run(neo4j=neo4j, llm=llm, domain="Servicing", trace_id="t-err")

    # Must not raise; must record the error in the summary; must not insert anything.
    assert summary["clusters_proposed"] == 0
    assert summary["clusters_skipped_dup"] == 0
    assert any("llm_failed" in e for e in summary["errors"])
    assert store["rows"] == []


@pytest.mark.asyncio
async def test_no_llm_skips():
    """Passing llm=None is a hard no-op — never raises."""
    consolidator = SynonymConsolidator()
    neo4j = AsyncMock()
    neo4j.run_query = AsyncMock(return_value=[])
    summary = await consolidator.run(neo4j=neo4j, llm=None, trace_id="t-none")
    assert summary["clusters_proposed"] == 0
    assert "no_llm" in summary["errors"]


# ---------------------------------------------------------------------------
# 3. Review endpoint — supersede + canonical create pattern
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_supersedes_non_canonical(monkeypatch):
    """A CONFIRM review must:
      1. Validate chosen_canonical_column is reachable from the cluster.
      2. UNWIND non-canonical members and SET effective_until + status='SUPERSEDED_BY_MERGE'
         on every live MAPS_TO out of them.
      3. Create a new CANONICAL MAPS_TO from the canonical BA to the chosen column.
    """
    from app.routes import catalog as cat

    canonical_attr = "Origination.LoanApplication.borrower_annual_income"
    other_attr = "Origination.CorrespondentPurchase.annual_household_income"
    canonical_col = "src1::orig.app.borrower_income"
    members = [canonical_attr, other_attr]

    proposal_row = {
        "proposal_id": "prop-1",
        "kind": "SYNONYM",
        "domain": "Origination",
        "members_json": members,  # _fetch unwraps JSON-typed columns
        "member_columns_json": [],
        "suggested_canonical_attr": canonical_attr,
        "suggested_canonical_column": canonical_col,
        "status": "PROPOSED",
    }

    fetch_calls: List[str] = []

    def fake_fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        fetch_calls.append(sql.strip().split("\n")[0])
        if "FROM synonym_proposals" in sql:
            return [proposal_row]
        if "FROM auditor_issues" in sql:
            return []  # no auditor issues to auto-resolve in this test
        return []

    class _UpdConn:
        def cursor(self):
            return _UpdCursor()
        def commit(self):
            pass
        def close(self):
            pass

    class _UpdCursor:
        def execute(self, *args, **kwargs):
            pass

    monkeypatch.setattr(cat, "_fetch", fake_fetch)
    monkeypatch.setattr(cat, "_conn", lambda: _UpdConn())

    # Build a Neo4j mock whose run_query side_effect returns the right rows
    # in order:
    #   1) column_check — count >= 1 to pass validation
    #   2) supersede UNWIND          → []
    #   3) secondary MERGE           → []
    #   4) max_version lookup        → [{"max_version": 0}]
    #   5) CANONICAL create          → []
    #   6+) per-non-canonical safe-delete check + delete → safe to delete
    neo4j = AsyncMock()
    call_log: List[Dict[str, Any]] = []

    async def fake_run_query(cypher: str, params=None, trace_id: str = ""):
        call_log.append({"cypher": cypher, "params": params or {}})
        c = cypher
        if "count(c) AS hits" in c:
            return [{"hits": 1}]
        if "max(m.version)" in c:
            return [{"max_version": 0}]
        if "count(e) AS attr_links" in c:
            # No HAS_ATTRIBUTE referrers and no TaskNode references → safe to delete.
            return [{"attr_links": 0, "task_refs": 0}]
        return []

    neo4j.run_query = AsyncMock(side_effect=fake_run_query)

    request = AsyncMock()
    request.headers = {"x-request-id": "trace-merge"}
    request.app.state.neo4j = neo4j

    body = cat.SynonymReviewRequest(
        action="CONFIRM",
        chosen_canonical_attr=canonical_attr,
        chosen_canonical_column=canonical_col,
        reviewed_by="alice",
    )
    result = await cat.review_synonym_proposal(
        proposal_id="prop-1", request=request, body=body,
    )

    # Endpoint contract.
    assert result["status"] == "APPLIED"
    assert result["canonical_attr"] == canonical_attr
    assert result["canonical_column"] == canonical_col
    assert other_attr in result["non_canonical"]

    cyphers = [c["cypher"] for c in call_log]
    # 1. Column-reachability check.
    assert any("count(c) AS hits" in cy for cy in cyphers)
    # 2. Supersede pattern fired with effective_until=datetime() and status='SUPERSEDED_BY_MERGE'.
    supersede_call = next(
        (c for c in call_log if "SUPERSEDED_BY_MERGE" in c["cypher"] and "UNWIND $non_canonical" in c["cypher"]),
        None,
    )
    assert supersede_call is not None, "expected a supersede UNWIND call"
    assert "m.effective_until = datetime()" in supersede_call["cypher"]
    assert supersede_call["params"]["non_canonical"] == [other_attr]
    assert supersede_call["params"]["canonical_attr_fq"] == canonical_attr

    # 3. Canonical CANONICAL MAPS_TO create with version = max+1 = 1.
    canonical_call = next(
        (c for c in call_log if "MERGE (ba)-[m:MAPS_TO {effective_until: null, status: 'CANONICAL'}]" in c["cypher"]),
        None,
    )
    assert canonical_call is not None, "expected canonical MAPS_TO MERGE"
    assert canonical_call["params"]["canonical_attr_fq"] == canonical_attr
    assert canonical_call["params"]["col_fq"] == canonical_col
    assert canonical_call["params"]["new_version"] == 1
    assert canonical_call["params"]["reviewed_by"] == "alice"

    # 4. Non-canonical BA without referrers gets DETACH DELETEd.
    delete_call = next(
        (c for c in call_log if "DETACH DELETE ba" in c["cypher"]),
        None,
    )
    assert delete_call is not None
    assert delete_call["params"]["fq"] == other_attr
    assert other_attr in result["deleted_bas"]
