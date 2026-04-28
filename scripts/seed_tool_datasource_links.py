"""Idempotently MERGE Tool→ACCESSES→DataSource edges in Neo4j.

The agent-mgmt toolService.linkToolToDataSource() auto-links on tool create/
update by matching tool.hostname against ds.source_uri / ds.source_name. Some
tools were registered before that hook existed, or have hostnames that don't
match the catalog naming scheme. This script lets you wire them up by name.

Default seeds (extend the SEEDS list at the bottom):
  "Home Lending Graph DB"  →  any DataSource with source_type='NEO4J'

Usage:
  python scripts/seed_tool_datasource_links.py

Reads NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD / NEO4J_DATABASE from .env or
the environment. Safe to re-run — every write uses MERGE.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

from neo4j import GraphDatabase


def _load_env() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _connect():
    uri = os.environ.get("NEO4J_URI")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")
    if not uri:
        print("ERROR: NEO4J_URI not set", file=sys.stderr)
        sys.exit(2)
    return GraphDatabase.driver(uri, auth=(user, password))


def link_tool_to_source_type(
    session,
    tool_name: str,
    source_type: str,
    source_name: Optional[str] = None,
) -> List[str]:
    """MERGE (t:Tool {name})-[:ACCESSES]->(ds:DataSource) for every DataSource
    matching `source_type` (and optionally `source_name`). Returns the list of
    source_names linked."""
    if source_name:
        query = """
            MATCH (t:Tool)
              WHERE t.name = $tool_name
            MATCH (ds:DataSource {source_name: $source_name})
            MERGE (t)-[r:ACCESSES]->(ds)
              ON CREATE SET r.bound_at = datetime(), r.refreshed_at = datetime()
              ON MATCH  SET r.refreshed_at = datetime()
            RETURN t.tool_id AS tool_id, ds.source_name AS source_name
        """
        params = {"tool_name": tool_name, "source_name": source_name}
    else:
        query = """
            MATCH (t:Tool)
              WHERE t.name = $tool_name
            MATCH (ds:DataSource {source_type: $source_type})
            MERGE (t)-[r:ACCESSES]->(ds)
              ON CREATE SET r.bound_at = datetime(), r.refreshed_at = datetime()
              ON MATCH  SET r.refreshed_at = datetime()
            RETURN t.tool_id AS tool_id, ds.source_name AS source_name
        """
        params = {"tool_name": tool_name, "source_type": source_type}
    rows = session.run(query, params).data()
    return [r["source_name"] for r in rows or []]


SEEDS = [
    # (tool_name, source_type, optional source_name)
    ("Home Lending Graph DB", "NEO4J", None),
]


def main() -> None:
    _load_env()
    driver = _connect()
    database = os.environ.get("NEO4J_DATABASE") or "neo4j"
    print(f"Linking tools to data sources in {database}...")
    try:
        with driver.session(database=database) as session:
            for tool_name, source_type, source_name in SEEDS:
                linked = link_tool_to_source_type(
                    session,
                    tool_name=tool_name,
                    source_type=source_type,
                    source_name=source_name,
                )
                if linked:
                    print(f"  [OK] {tool_name!r} -> {len(linked)} source(s): {linked}")
                else:
                    print(
                        f"  [SKIP] {tool_name!r} — no Tool node with that name "
                        f"OR no DataSource with source_type={source_type}"
                    )
    finally:
        driver.close()


if __name__ == "__main__":
    main()
