"""Ontology version helpers (Phase E4).

The Business Ontology graph stores ``(:BusinessAttribute)-[:MAPS_TO]->(:DataColumn)``
edges with versioning metadata: ``version: int``, ``effective_from: datetime``,
``effective_until: datetime|null``. Edges with ``effective_until IS NULL`` are
the *current* mapping; superseded edges retain their value of
``effective_until`` for replay/audit.

These helpers are read-only: the writes themselves live in
``crawler/catalog_writer.py`` (auto-mappings) and ``routes/catalog.py``
(auditor reviews — confirm/correct/reject implement the supersede pattern).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.utils.logger import logger


async def get_current_version(
    neo4j: Any,
    attribute_fq_name: str,
    column_fq_name: str,
    trace_id: str = "",
) -> Optional[int]:
    """Return the current (effective_until IS NULL) version for a mapping.

    Returns ``None`` if there is no live edge between the attribute and the
    column (e.g. the mapping has been REJECTED and not replaced).
    """
    cypher = """
    MATCH (ba:BusinessAttribute {fq_name: $attribute_fq_name})
          -[m:MAPS_TO]->(c:DataColumn {fq_name: $column_fq_name})
    WHERE m.effective_until IS NULL
    RETURN coalesce(m.version, 1) AS version
    LIMIT 1
    """
    try:
        rows = await neo4j.run_query(
            cypher,
            {
                "attribute_fq_name": attribute_fq_name,
                "column_fq_name": column_fq_name,
            },
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning(
            "get_current_version failed",
            layer="service",
            error=str(exc),
            attribute_fq_name=attribute_fq_name,
            column_fq_name=column_fq_name,
            trace_id=trace_id,
        )
        return None
    if not rows:
        return None
    v = rows[0].get("version")
    return int(v) if v is not None else None


async def get_history(
    neo4j: Any,
    attribute_fq_name: str,
    trace_id: str = "",
) -> List[Dict[str, Any]]:
    """Return the full version timeline for a BusinessAttribute.

    Each row: ``{version, status, confidence, reviewed_by, effective_from,
    effective_until, column_fq_name}``. Ordered by version ascending. Includes
    superseded (``effective_until IS NOT NULL``) and current edges.
    """
    cypher = """
    MATCH (ba:BusinessAttribute {fq_name: $attribute_fq_name})
          -[m:MAPS_TO]->(c:DataColumn)
    RETURN coalesce(m.version, 1)  AS version,
           m.status                AS status,
           m.confidence            AS confidence,
           m.reviewed_by           AS reviewed_by,
           m.effective_from        AS effective_from,
           m.effective_until       AS effective_until,
           c.fq_name               AS column_fq_name
    ORDER BY version ASC, effective_from ASC
    """
    try:
        rows = await neo4j.run_query(
            cypher,
            {"attribute_fq_name": attribute_fq_name},
            trace_id=trace_id,
        )
    except Exception as exc:
        logger.warning(
            "get_history failed",
            layer="service",
            error=str(exc),
            attribute_fq_name=attribute_fq_name,
            trace_id=trace_id,
        )
        return []

    out: List[Dict[str, Any]] = []
    for r in rows or []:
        rec = dict(r)
        # Convert datetime-like values to ISO strings so the result is JSON-safe.
        for key in ("effective_from", "effective_until"):
            v = rec.get(key)
            if v is not None and hasattr(v, "isoformat"):
                rec[key] = v.isoformat()
        out.append(rec)
    return out
