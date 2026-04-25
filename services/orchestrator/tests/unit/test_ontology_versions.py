"""Unit tests for Phase E4 ontology versioning.

These cover the version-related behaviors of the catalog writer (auto-mapping
edge creation), the auditor review path (supersede pattern), and the
ontology_versions helper module.

We test against a mock Neo4j adapter — the real Cypher is exercised in the
integration suite.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

from app.services.crawler.base import CrawledAsset, CrawledColumn, CrawlResult
from app.services.crawler.catalog_writer import CatalogWriter
from app.services.crawler.semantic_mapper import (
    AssetProposal,
    ProposedMapping,
)
from app.services.ontology_versions import get_current_version, get_history


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_proposal() -> AssetProposal:
    asset = CrawledAsset(
        source_name="test_db",
        source_uri="mysql://test/test_db",
        asset_type="TABLE",
        schema_name="sales",
        asset_name="orders",
        fully_qualified="sales.orders",
        row_count=100,
        comment="orders table",
        columns=[
            CrawledColumn(
                name="customer_id",
                data_type="int",
                nullable=False,
                ordinal=1,
                is_pk=False,
                is_fk=True,
                fk_references="sales.customers.id",
                sample_values=["1", "2"],
                comment="",
            )
        ],
    )
    mapping = ProposedMapping(
        column_name="customer_id",
        domain="Sales",
        entity="Order",
        attribute="customer_id",
        confidence=0.92,
        reasoning="exact name match",
    )
    return AssetProposal(
        asset=asset,
        domain="Sales",
        entity="Order",
        columns=[mapping],
        model_version="test-v1",
    )


def _make_crawl() -> CrawlResult:
    return CrawlResult(
        source_name="test_db",
        source_type="MYSQL",
        source_uri="mysql://test/test_db",
        assets=[_make_proposal().asset],
    )


# ---------------------------------------------------------------------------
# catalog_writer.py — auto-mapping edges stamp version=1 + effective_from
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_creation_sets_version_1(mock_neo4j, monkeypatch):
    """A brand-new MAPS_TO MERGE must coalesce version=1 and effective_from.

    The writer issues parameterized Cypher; we just assert the snippet that
    encodes the versioning invariant is present in the call. Existing
    pre-Phase-E4 edges with no version property get version=1 on next touch
    via the same COALESCE.
    """
    writer = CatalogWriter(neo4j=mock_neo4j)
    # Bypass the MySQL audit-row insert so the test stays in-process.
    monkeypatch.setattr(writer, "_mysql", lambda: _DummyMysql())

    crawl = _make_crawl()
    proposal = _make_proposal()
    await writer._write_proposal(
        crawl=crawl, proposal=proposal,
        run_id="run-1", crawler_id="crawler-1", trace_id="t-1",
    )

    # Find the run_query call that targets MAPS_TO.
    maps_to_calls = [
        c for c in mock_neo4j.run_query.await_args_list
        if "MAPS_TO" in c.args[0] and "MERGE (ba)-[m:MAPS_TO" in c.args[0]
    ]
    assert maps_to_calls, "expected at least one MAPS_TO MERGE call"
    cypher = maps_to_calls[0].args[0]

    # Versioning invariants
    assert "coalesce(m.version, 1)" in cypher
    assert "coalesce(m.effective_from, datetime())" in cypher
    # Live-edge filter on the MERGE side so we don't grab a superseded edge.
    assert "MERGE (ba)-[m:MAPS_TO {effective_until: null}]->(c)" in cypher


# ---------------------------------------------------------------------------
# routes/catalog.py — auditor CORRECT supersedes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correction_supersedes_old_version():
    """A CORRECT review closes the OLD edge and creates a NEW edge with
    version = old.version + 1."""
    from app.routes import catalog as catalog_routes

    neo4j = AsyncMock()
    # 1st call: lookup of asset_fq from fully_qualified
    # 2nd call: SET effective_until on old edge → returns old_version=3
    # 3rd call: CREATE new MAPS_TO with version=4
    neo4j.run_query = AsyncMock(
        side_effect=[
            [{"asset_fq": "test_db::sales.orders"}],
            [{"old_version": 3}],
            [],
        ]
    )

    # Drive the same code path the route uses by calling the inner block via
    # a fake Request — easier to just assert against the Cypher emitted by
    # the route directly. We invoke the route function with a minimal mock
    # Request that exposes app.state.neo4j, plus a mock MySQL fetcher and
    # connection.
    request = AsyncMock()
    request.headers = {"x-request-id": "trace-corr"}
    request.app.state.neo4j = neo4j

    decision = {
        "data_source": "mysql://test/test_db",
        "data_asset": "sales.orders",
        "data_column": "customer_id",
        "proposed_domain": "Sales",
        "proposed_entity": "Order",
        "proposed_attribute": "customer_id",
    }

    def fake_fetch(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
        if sql.strip().startswith("SELECT * FROM semantic_mapping_decisions"):
            return [decision]
        return []

    class _DummyConn:
        def cursor(self):
            return _DummyCursor()
        def commit(self):
            pass
        def close(self):
            pass

    class _DummyCursor:
        def execute(self, *args, **kwargs):
            pass

    import app.routes.catalog as cat
    orig_fetch = cat._fetch
    orig_conn = cat._conn
    cat._fetch = fake_fetch
    cat._conn = lambda: _DummyConn()
    try:
        body = catalog_routes.MappingReviewRequest(
            action="CORRECT",
            auditor_domain="Sales",
            auditor_entity="Order",
            auditor_attribute="buyer_id",  # changed
            reviewed_by="alice",
        )
        await catalog_routes.review_mapping_decision(
            decision_id="dec-1", request=request, body=body,
        )
    finally:
        cat._fetch = orig_fetch
        cat._conn = orig_conn

    cypher_calls = [c.args[0] for c in neo4j.run_query.await_args_list]
    # Expect three Cypher calls: asset lookup, supersede SET, CREATE new.
    assert len(cypher_calls) >= 3
    # Old edge gets effective_until + status=SUPERSEDED.
    supersede = cypher_calls[1]
    assert "m.effective_until = datetime()" in supersede
    assert "$supersede_status" in supersede
    # New edge is CREATEd with version = old + 1 (3 + 1 = 4).
    create = cypher_calls[2]
    assert "CREATE (ba)-[m:MAPS_TO" in create
    assert "version: $new_version" in create
    assert "effective_until: null" in create
    # Confirm the version param itself is 4.
    create_params = neo4j.run_query.await_args_list[2].args[1]
    assert create_params["new_version"] == 4


# ---------------------------------------------------------------------------
# ontology_versions.get_current_version ignores superseded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_version_ignores_superseded():
    """Helper must filter on effective_until IS NULL."""
    neo4j = AsyncMock()
    neo4j.run_query = AsyncMock(return_value=[{"version": 7}])

    v = await get_current_version(
        neo4j,
        attribute_fq_name="Sales.Order.customer_id",
        column_fq_name="test_db::sales.orders.customer_id",
    )
    assert v == 7

    cypher = neo4j.run_query.await_args_list[0].args[0]
    assert "effective_until IS NULL" in cypher
    # Parameterized — no string interpolation of fq_names.
    params = neo4j.run_query.await_args_list[0].args[1]
    assert params["attribute_fq_name"] == "Sales.Order.customer_id"
    assert params["column_fq_name"] == "test_db::sales.orders.customer_id"


@pytest.mark.asyncio
async def test_get_current_version_returns_none_when_no_live_edge():
    neo4j = AsyncMock()
    neo4j.run_query = AsyncMock(return_value=[])

    v = await get_current_version(
        neo4j, attribute_fq_name="X.Y.z", column_fq_name="db::s.t.c",
    )
    assert v is None


@pytest.mark.asyncio
async def test_get_history_returns_all_versions_ordered():
    """History helper must return both superseded AND current edges, ordered
    by version ascending."""
    neo4j = AsyncMock()
    neo4j.run_query = AsyncMock(
        return_value=[
            {
                "version": 1, "status": "AUTO_ACCEPTED", "confidence": 0.7,
                "reviewed_by": None, "effective_from": "2026-01-01T00:00:00",
                "effective_until": "2026-02-01T00:00:00",
                "column_fq_name": "db::s.t.c",
            },
            {
                "version": 2, "status": "CONFIRMED", "confidence": 1.0,
                "reviewed_by": "alice", "effective_from": "2026-02-01T00:00:00",
                "effective_until": None,
                "column_fq_name": "db::s.t.c",
            },
        ],
    )

    rows = await get_history(neo4j, attribute_fq_name="Sales.Order.customer_id")
    assert len(rows) == 2
    assert rows[0]["version"] == 1
    assert rows[0]["effective_until"] is not None
    assert rows[1]["version"] == 2
    assert rows[1]["effective_until"] is None

    cypher = neo4j.run_query.await_args_list[0].args[0]
    # No effective_until filter — history shows everything.
    assert "ORDER BY version ASC" in cypher
    assert "WHERE m.effective_until" not in cypher


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _DummyMysql:
    """Stand-in for the MySQL connection in tests so we don't hit the network."""

    def cursor(self):
        return self

    def executemany(self, *args, **kwargs):
        return None

    def commit(self):
        return None

    def close(self):
        return None
