"""Phase F5 — Post-crawl synonym consolidation pass.

After every successful crawl (and on demand from the UI), walk all
``(:BusinessAttribute)`` nodes in Neo4j and ask an LLM to cluster names that
mean the same thing within a single business domain. Three flavors are
recognized:

  * SYNONYM     — same concept, different physical names
                  (e.g. ``borrower_annual_income`` vs ``annual_household_income``)
  * DUPLICATION — same physical name across many tables
                  (e.g. ``loan_id`` everywhere)
  * GRAIN       — same/different name across tables with different grain
                  (daily / monthly / annual / history / backup)

Each cluster the LLM returns is materialized as a row in
``synonym_proposals`` with ``status='PROPOSED'``. A Data Steward then picks
the canonical BusinessAttribute name + canonical physical column via the
``POST /v1/catalog/synonym-proposals/{id}/review`` endpoint, which fires the
MERGE / supersede pattern in Neo4j.

Idempotency: if a cluster's exact ``members_json`` set already has a row in
any non-terminal status (``PROPOSED`` / ``IN_REVIEW`` / ``CONFIRMED``), we
skip the insert. The cluster fingerprint is the sorted JSON of fq_names.

LLM safety:
  * Time-boxed via ``asyncio.wait_for(..., 60.0)``.
  * On any error we log and skip — consolidation never raises.
  * Chunked to ~50 BAs per LLM call to keep the prompt within budget.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import mysql.connector

from app.adapters.llm_adapter import LLMAdapter
from app.adapters.neo4j_adapter import Neo4jAdapter
from app.config import settings

logger = logging.getLogger("pmos.crawler.synonym_consolidator")

_SYSTEM_PROMPT = (
    "You are clustering business attribute names that mean the same thing in "
    "the same business domain. Three kinds: SYNONYM, DUPLICATION, GRAIN. "
    "Return strict JSON: {clusters:[{kind, members:[fq_name,...], "
    "suggested_canonical_attr, suggested_canonical_column, rationale, "
    "confidence}]}"
)

# Hard cap to keep one LLM prompt manageable.
_MAX_BAS_PER_CALL = 50
_LLM_TIMEOUT_SECS = 60.0
_NON_TERMINAL_STATUSES = ("PROPOSED", "IN_REVIEW", "CONFIRMED")


@dataclass
class _BARecord:
    """In-memory row for one BusinessAttribute and its (most-recent) physical column(s)."""

    fq_name: str
    name: str
    domain: str
    entity: str
    columns: List[Dict[str, Any]] = field(default_factory=list)


class SynonymConsolidator:
    """Cluster BusinessAttribute names into synonym/duplication/grain proposals."""

    def __init__(self) -> None:
        pass

    # ------------------------------------------------------------------
    # MySQL helper (short-lived connection, same pattern as catalog_writer)
    # ------------------------------------------------------------------
    def _mysql(self):
        return mysql.connector.connect(
            host=settings.mysql_host,
            port=settings.mysql_port,
            user=settings.mysql_user,
            password=settings.mysql_password,
            database=settings.mysql_db,
            connection_timeout=10,
        )

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def run(
        self,
        neo4j: Neo4jAdapter,
        llm: Optional[LLMAdapter],
        *,
        domain: Optional[str] = None,
        trace_id: str = "",
    ) -> Dict[str, Any]:
        """Walk BAs, cluster via one LLM call (per ~50 BAs / per domain), insert proposals.

        Returns a small summary dict — never raises.
        """
        summary: Dict[str, Any] = {
            "domain_filter": domain,
            "ba_total": 0,
            "clusters_proposed": 0,
            "clusters_skipped_dup": 0,
            "errors": [],
        }
        if llm is None:
            logger.info(
                "SynonymConsolidator skipped — no LLM adapter",
                extra={"trace_id": trace_id},
            )
            summary["errors"].append("no_llm")
            return summary

        try:
            ba_records = await self._fetch_ba_records(neo4j, domain=domain, trace_id=trace_id)
        except Exception as exc:
            logger.warning(
                "SynonymConsolidator BA fetch failed: %s",
                exc,
                extra={"trace_id": trace_id, "domain": domain},
            )
            summary["errors"].append(f"fetch_failed: {exc}")
            return summary

        summary["ba_total"] = len(ba_records)
        if not ba_records:
            return summary

        # Group by domain so each LLM call sees one domain at a time, then
        # chunk if a single domain has more than _MAX_BAS_PER_CALL records.
        by_domain: Dict[str, List[_BARecord]] = {}
        for r in ba_records:
            by_domain.setdefault(r.domain or "General", []).append(r)

        for dom, bas in by_domain.items():
            for chunk in _chunked(bas, _MAX_BAS_PER_CALL):
                try:
                    clusters = await self._cluster_via_llm(
                        llm=llm, domain=dom, bas=chunk, trace_id=trace_id,
                    )
                except Exception as exc:
                    logger.warning(
                        "SynonymConsolidator LLM failed (skipped): %s",
                        exc,
                        extra={"trace_id": trace_id, "domain": dom, "n_bas": len(chunk)},
                    )
                    summary["errors"].append(f"llm_failed:{dom}:{exc}")
                    continue

                for cluster in clusters:
                    inserted = self._insert_proposal_if_new(
                        cluster=cluster,
                        domain=dom,
                        ba_records=chunk,
                        trace_id=trace_id,
                    )
                    if inserted:
                        summary["clusters_proposed"] += 1
                    else:
                        summary["clusters_skipped_dup"] += 1

        logger.info(
            "SynonymConsolidator complete",
            extra={
                "trace_id": trace_id,
                "domain_filter": domain,
                "ba_total": summary["ba_total"],
                "clusters_proposed": summary["clusters_proposed"],
                "clusters_skipped_dup": summary["clusters_skipped_dup"],
                "errors": len(summary["errors"]),
            },
        )
        return summary

    # ------------------------------------------------------------------
    # Neo4j fetch
    # ------------------------------------------------------------------
    async def _fetch_ba_records(
        self,
        neo4j: Neo4jAdapter,
        *,
        domain: Optional[str],
        trace_id: str,
    ) -> List[_BARecord]:
        """Pull every (live) BusinessAttribute and its current physical columns.

        We collect *only* edges with ``effective_until IS NULL`` so superseded
        mappings don't contaminate the clusters.
        """
        cypher = """
        MATCH (ba:BusinessAttribute)
        WHERE $domain = '' OR ba.domain = $domain
        OPTIONAL MATCH (ba)-[m:MAPS_TO]->(c:DataColumn)
          WHERE m.effective_until IS NULL
        OPTIONAL MATCH (c)<-[:HAS_COLUMN]-(a:DataAsset)
        OPTIONAL MATCH (a)<-[:HAS_ASSET]-(s:DataSource)
        WITH ba, collect({
          column_fq_name: c.fq_name,
          column_name: c.name,
          data_type: c.data_type,
          sample_values: c.sample_values,
          asset_fq_name: a.fq_name,
          source_name: s.source_name,
          source_uri: s.source_uri,
          mapping_status: m.status
        }) AS columns
        RETURN ba.fq_name AS fq_name,
               ba.name    AS name,
               ba.domain  AS domain,
               ba.entity  AS entity,
               columns
        """
        rows = await neo4j.run_query(
            cypher,
            {"domain": domain or ""},
            trace_id=trace_id,
        )
        records: List[_BARecord] = []
        for r in rows or []:
            cols = []
            for c in (r.get("columns") or []):
                # Drop placeholder rows where the OPTIONAL MATCH found nothing.
                if not c or not c.get("column_fq_name"):
                    continue
                cols.append({
                    "column_fq_name": c.get("column_fq_name"),
                    "column_name": c.get("column_name"),
                    "data_type": c.get("data_type"),
                    "sample_values": (c.get("sample_values") or [])[:3],
                    "asset_fq_name": c.get("asset_fq_name"),
                    "source_name": c.get("source_name"),
                    "source_uri": c.get("source_uri"),
                    "mapping_status": c.get("mapping_status"),
                })
            records.append(_BARecord(
                fq_name=r.get("fq_name") or "",
                name=r.get("name") or "",
                domain=r.get("domain") or "General",
                entity=r.get("entity") or "",
                columns=cols,
            ))
        # Drop BAs with no live columns AND no name — they're dangling artifacts.
        records = [r for r in records if r.fq_name]
        return records

    # ------------------------------------------------------------------
    # LLM call
    # ------------------------------------------------------------------
    async def _cluster_via_llm(
        self,
        *,
        llm: LLMAdapter,
        domain: str,
        bas: List[_BARecord],
        trace_id: str,
    ) -> List[Dict[str, Any]]:
        """Single time-boxed LLM call returning the parsed ``clusters`` list.

        Empty list on parse failure or empty response.
        """
        prompt = self._build_prompt(domain=domain, bas=bas)
        raw = await asyncio.wait_for(
            llm.complete(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
                max_tokens=2000,
                trace_id=trace_id,
            ),
            timeout=_LLM_TIMEOUT_SECS,
        )
        if not raw:
            return []
        parsed = self._parse_response(raw)
        clusters = parsed.get("clusters") or []
        # Defensive: ensure each cluster has a ``members`` list of strings.
        cleaned: List[Dict[str, Any]] = []
        known_fqs = {r.fq_name for r in bas}
        for c in clusters:
            if not isinstance(c, dict):
                continue
            members = c.get("members") or []
            if not isinstance(members, list):
                continue
            members = [str(m) for m in members if isinstance(m, str)]
            # Filter out hallucinated fq_names (LLM occasionally invents).
            members = [m for m in members if m in known_fqs]
            if len(members) < 2:
                # A cluster of one is not a synonym — skip.
                continue
            kind = str(c.get("kind") or "SYNONYM").upper()
            if kind not in ("SYNONYM", "DUPLICATION", "GRAIN", "NAMING", "OTHER"):
                kind = "OTHER"
            try:
                conf = float(c.get("confidence", 0.5))
            except Exception:
                conf = 0.5
            conf = max(0.0, min(1.0, conf))
            cleaned.append({
                "kind": kind,
                "members": members,
                "suggested_canonical_attr": str(c.get("suggested_canonical_attr") or "")[:255],
                "suggested_canonical_column": str(c.get("suggested_canonical_column") or "")[:512],
                "rationale": str(c.get("rationale") or "")[:2000],
                "confidence": conf,
            })
        return cleaned

    def _build_prompt(self, *, domain: str, bas: List[_BARecord]) -> str:
        lines: List[str] = []
        lines.append(f"Business domain: {domain}")
        lines.append(f"Number of attributes: {len(bas)}")
        lines.append("")
        lines.append("Each entry is one BusinessAttribute (fq_name) and its current "
                     "physical column bindings, with up to 3 sample values.")
        lines.append("")
        for r in bas:
            lines.append(f"- fq_name: {r.fq_name}")
            lines.append(f"    name: {r.name}    entity: {r.entity}")
            for col in r.columns[:3]:
                samples = col.get("sample_values") or []
                lines.append(
                    f"    column: {col.get('column_fq_name')}  "
                    f"(type={col.get('data_type')}, samples={samples})"
                )
        lines.append("")
        lines.append(
            "Cluster these into groups that mean the same thing. Three kinds:"
        )
        lines.append(
            "  SYNONYM     — same concept, different physical names "
            "(e.g. borrower_annual_income vs annual_household_income)."
        )
        lines.append(
            "  DUPLICATION — same physical name reused across many tables "
            "(e.g. loan_id everywhere)."
        )
        lines.append(
            "  GRAIN       — same/different name across tables with different grain "
            "(daily / monthly / annual / history / backup)."
        )
        lines.append("")
        lines.append("Respond with strict JSON, no prose, this exact shape:")
        lines.append(
            '{"clusters":['
            '{"kind":"SYNONYM",'
            '"members":["<fq_name>","<fq_name>",...],'
            '"suggested_canonical_attr":"<name the canonical BusinessAttribute>",'
            '"suggested_canonical_column":"<best physical column fq_name>",'
            '"rationale":"<one short sentence>",'
            '"confidence":0.0}]}'
        )
        lines.append(
            "Rules: (1) only include clusters with >= 2 members; "
            "(2) every fq_name in 'members' MUST come from the list above — "
            "do NOT invent names; (3) suggested_canonical_attr should be a "
            "snake_case business name (it can match an existing member's name "
            "or be a new clearer name)."
        )
        return "\n".join(lines)

    def _parse_response(self, raw: str) -> Dict[str, Any]:
        if not raw:
            return {}
        # Direct parse first.
        try:
            return json.loads(raw.strip())
        except Exception:
            pass
        # Fall back: first balanced {...} block.
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception:
                return {}
        return {}

    # ------------------------------------------------------------------
    # MySQL insert with idempotency check
    # ------------------------------------------------------------------
    def _cluster_fingerprint(self, members: List[str]) -> str:
        """Stable fingerprint for dedupe — sorted JSON of fq_names."""
        return json.dumps(sorted(members), separators=(",", ":"))

    def _insert_proposal_if_new(
        self,
        *,
        cluster: Dict[str, Any],
        domain: str,
        ba_records: List[_BARecord],
        trace_id: str,
    ) -> bool:
        """Insert one synonym_proposals row. Returns True if inserted, False if dup-skipped."""
        members: List[str] = cluster.get("members") or []
        if len(members) < 2:
            return False

        fingerprint = self._cluster_fingerprint(members)

        # Build the member_columns_json side-table — one entry per (ba, column).
        ba_lookup: Dict[str, _BARecord] = {r.fq_name: r for r in ba_records}
        member_columns: List[Dict[str, Any]] = []
        for fq in members:
            r = ba_lookup.get(fq)
            if not r:
                continue
            for c in r.columns:
                member_columns.append({
                    "ba_fq_name": fq,
                    "column_fq_name": c.get("column_fq_name"),
                    "source_uri": c.get("source_uri"),
                    "sample_values": c.get("sample_values") or [],
                })

        try:
            conn = self._mysql()
        except Exception as exc:
            logger.warning(
                "SynonymConsolidator MySQL connect failed (skipped): %s",
                exc,
                extra={"trace_id": trace_id},
            )
            return False
        try:
            cur = conn.cursor()
            # Idempotency: look for ANY non-terminal row whose members_json
            # (sorted) equals our fingerprint. We rely on JSON_EXTRACT to
            # compare, and pre-store all members_json sorted to make the
            # comparison stable.
            placeholders = ",".join(["%s"] * len(_NON_TERMINAL_STATUSES))
            cur.execute(
                f"""
                SELECT proposal_id
                FROM synonym_proposals
                WHERE status IN ({placeholders})
                  AND CAST(members_json AS CHAR) = %s
                LIMIT 1
                """,
                tuple(_NON_TERMINAL_STATUSES) + (fingerprint,),
            )
            row = cur.fetchone()
            if row:
                logger.info(
                    "SynonymConsolidator dedupe — cluster already proposed",
                    extra={
                        "trace_id": trace_id,
                        "existing_proposal_id": row[0],
                        "members": members,
                    },
                )
                return False

            proposal_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO synonym_proposals
                  (proposal_id, kind, domain, members_json, member_columns_json,
                   suggested_canonical_attr, suggested_canonical_column,
                   rationale, confidence, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'PROPOSED')
                """,
                (
                    proposal_id,
                    cluster.get("kind", "SYNONYM"),
                    domain,
                    fingerprint,  # store sorted form for stable dedupe
                    json.dumps(member_columns, default=str),
                    cluster.get("suggested_canonical_attr") or None,
                    cluster.get("suggested_canonical_column") or None,
                    cluster.get("rationale") or None,
                    float(cluster.get("confidence") or 0.0),
                ),
            )
            conn.commit()
            logger.info(
                "SynonymConsolidator proposal inserted",
                extra={
                    "trace_id": trace_id,
                    "proposal_id": proposal_id,
                    "kind": cluster.get("kind"),
                    "domain": domain,
                    "members": members,
                },
            )
            return True
        except Exception as exc:
            logger.warning(
                "SynonymConsolidator insert failed (skipped): %s",
                exc,
                extra={"trace_id": trace_id, "members": members},
            )
            return False
        finally:
            try:
                conn.close()
            except Exception:
                pass


def _chunked(seq: List[Any], size: int) -> List[List[Any]]:
    if size <= 0:
        return [seq]
    return [seq[i:i + size] for i in range(0, len(seq), size)]
