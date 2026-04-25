"""Factory for the Business Ontology Neo4j adapter.

The ontology graph is logically separate from the execution graph but in dev
defaults to the same Neo4j instance. Each ``ontology_neo4j_*`` setting falls
back to its execution-graph counterpart so a single connection string Just
Works without configuration noise.
"""

from __future__ import annotations

from app.adapters.neo4j_adapter import Neo4jAdapter
from app.config import settings


def build_ontology_adapter() -> Neo4jAdapter:
    return Neo4jAdapter(
        name="ontology",
        uri=settings.ontology_neo4j_uri or settings.neo4j_uri,
        user=settings.ontology_neo4j_user or settings.neo4j_user,
        password=settings.ontology_neo4j_password or settings.neo4j_password,
        database=settings.ontology_neo4j_database or settings.neo4j_database,
    )
