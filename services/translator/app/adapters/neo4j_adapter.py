"""Neo4j async driver wrapper for the Translator service.

The translator queries the *ontology* graph (entities, relationships, dataset
bindings). In dev the ontology and execution graphs share an instance; this
adapter falls back from ONTOLOGY_NEO4J_* to NEO4J_* exactly like the
orchestrator's ``ontology_neo4j`` factory does.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neo4j import AsyncDriver, AsyncGraphDatabase

from app.config import settings
from app.utils.logger import logger


class OntologyNeo4jAdapter:
    """Async Neo4j wrapper bound to the Business Ontology graph."""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database: Optional[str] = None,
    ) -> None:
        self._driver: Optional[AsyncDriver] = None
        self.name = "ontology"
        self._uri = uri if uri is not None else (settings.ontology_neo4j_uri or settings.neo4j_uri)
        self._user = user if user is not None else (settings.ontology_neo4j_user or settings.neo4j_user)
        self._password = password if password is not None else (
            settings.ontology_neo4j_password or settings.neo4j_password
        )
        self._database = database if database is not None else (
            settings.ontology_neo4j_database or settings.neo4j_database
        )

    async def connect(self) -> None:
        if not self._uri:
            logger.warning(
                "Neo4j URI not configured — adapter will be in degraded mode",
                layer="adapter",
                name=self.name,
            )
            return
        self._driver = AsyncGraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
        )
        logger.info(
            "Neo4j driver initialised",
            layer="adapter",
            name=self.name,
            target=self._uri,
        )

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            logger.info("Neo4j driver closed", layer="adapter", name=self.name)

    async def health_check(self) -> bool:
        if not self._driver:
            return False
        try:
            async with self._driver.session(database=self._database) as session:
                await session.run("RETURN 1")
            return True
        except Exception as exc:
            logger.error(
                "Neo4j health check failed",
                layer="adapter",
                name=self.name,
                error=str(exc),
            )
            return False

    async def run_query(
        self,
        cypher: str,
        parameters: Optional[Dict[str, Any]] = None,
        trace_id: str = "",
    ) -> List[Dict[str, Any]]:
        """Execute a Cypher query and return list of record dicts."""
        if not self._driver:
            raise RuntimeError("Neo4j driver not connected")
        params = parameters or {}
        async with self._driver.session(database=self._database) as session:
            result = await session.run(cypher, **params)
            records = await result.data()
        logger.debug(
            "Neo4j query executed",
            layer="adapter",
            name=self.name,
            cypher=cypher[:120],
            rows=len(records),
            trace_id=trace_id,
        )
        return records


def build_ontology_adapter() -> OntologyNeo4jAdapter:
    """Factory mirroring the orchestrator's ``build_ontology_adapter``."""
    return OntologyNeo4jAdapter()
