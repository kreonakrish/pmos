"""LLM-powered semantic mapper.

Takes a crawled asset (table + its columns + sample values) and asks an LLM
to propose a BusinessDomain, BusinessEntity, and BusinessAttribute for each
column, plus a confidence score. Returns structured ProposedMapping objects
that the CatalogWriter then persists into Neo4j and MySQL audit rows.

The prompt is deliberately strict about JSON output — we parse the response
and tolerate minor formatting issues by extracting the first JSON object.
On LLM failure, the mapper falls back to a heuristic name-based guesser so
crawls always produce *some* output for the auditor to look at.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.adapters.llm_adapter import LLMAdapter
from app.services.crawler.base import CrawledAsset, CrawledColumn

logger = logging.getLogger("pmos.crawler.mapper")


@dataclass
class ProposedMapping:
    column_name: str
    domain: str
    entity: str
    attribute: str
    confidence: float
    reasoning: str = ""


@dataclass
class AssetProposal:
    asset: CrawledAsset
    domain: str
    entity: str
    columns: List[ProposedMapping] = field(default_factory=list)
    model_version: str = ""


class SemanticMapper:
    """Asks an LLM to map crawled columns to business entities/attributes.

    The mapper is single-LLM-call-per-table for efficiency: one prompt
    describing the whole table (name + comments + columns + samples) and
    one JSON response with all columns mapped. This is ~40x cheaper than
    one call per column for a 15-column table.
    """

    def __init__(self, llm: Optional[LLMAdapter] = None, model: Optional[str] = None) -> None:
        self._llm = llm
        self._model = model  # None → use settings.llm_model default

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    async def map_asset(
        self,
        asset: CrawledAsset,
        trace_id: str = "",
    ) -> AssetProposal:
        if self._llm is None or not asset.columns:
            return self._heuristic_fallback(asset, reason="no_llm")

        try:
            prompt = self._build_prompt(asset)
            raw = await self._llm.complete(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=self._model,
                temperature=0.1,
                max_tokens=1500,
                trace_id=trace_id,
            )
            parsed = self._parse_response(raw)
            return self._proposal_from_parsed(asset, parsed, model_version=(self._model or "default"))
        except Exception as exc:
            logger.warning(
                "SemanticMapper LLM call failed for %s: %s — falling back to heuristic",
                asset.fully_qualified, exc,
            )
            return self._heuristic_fallback(asset, reason=f"llm_error: {exc}")

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------
    def _build_prompt(self, asset: CrawledAsset) -> str:
        lines: List[str] = []
        lines.append(f"Table: {asset.fully_qualified}")
        if asset.comment:
            lines.append(f"Table comment: {asset.comment}")
        if asset.row_count is not None:
            lines.append(f"Row count (approx): {asset.row_count}")
        lines.append("")
        lines.append("Columns:")
        for col in asset.columns:
            flags = []
            if col.is_pk:
                flags.append("PK")
            if col.is_fk:
                flags.append(f"FK->{col.fk_references}")
            if not col.nullable:
                flags.append("NOT NULL")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            samples = ""
            if col.sample_values:
                clipped = [str(v)[:40] for v in col.sample_values[:3]]
                samples = f"  samples: {clipped}"
            comment = f"  comment: {col.comment}" if col.comment else ""
            lines.append(
                f"  - {col.name} ({col.data_type}){flag_str}{samples}{comment}"
            )
        lines.append("")
        lines.append(
            "Based on the table name, column names, and sample values, respond "
            "with a SINGLE JSON object with this exact shape:"
        )
        lines.append("""{
  "domain": "<business domain, e.g. Servicing / Origination / Sales / Marketing>",
  "entity": "<canonical business entity, e.g. Loan / Borrower / Investor / Payment>",
  "columns": [
    {
      "column": "<exact column name from the list above>",
      "attribute": "<human-readable business attribute, e.g. current_balance>",
      "confidence": <float 0.0-1.0>,
      "reasoning": "<one short sentence>"
    }
  ]
}""")
        lines.append(
            "Rules: (1) use domain/entity names that would be reusable across "
            "related tables; (2) keep attribute names snake_case; (3) confidence "
            "below 0.5 means you are guessing; (4) return valid JSON only, no "
            "prose before or after."
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------
    def _parse_response(self, raw: str) -> Dict[str, Any]:
        if not raw:
            raise ValueError("empty LLM response")
        # Try direct parse first.
        try:
            return json.loads(raw.strip())
        except Exception:
            pass
        # Fall back: extract first balanced {...} block
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise ValueError(f"no JSON object found in response: {raw[:200]}")

    def _proposal_from_parsed(
        self,
        asset: CrawledAsset,
        parsed: Dict[str, Any],
        model_version: str,
    ) -> AssetProposal:
        domain = str(parsed.get("domain") or "General").strip() or "General"
        entity = str(parsed.get("entity") or asset.asset_name).strip() or asset.asset_name
        col_list = parsed.get("columns") or []

        # Build a lookup of actual column names so we don't accept hallucinated ones.
        known = {c.name: c for c in asset.columns}
        mappings: List[ProposedMapping] = []
        for item in col_list:
            if not isinstance(item, dict):
                continue
            col_name = str(item.get("column", "")).strip()
            if col_name not in known:
                continue
            attribute = str(item.get("attribute") or col_name).strip() or col_name
            try:
                conf = float(item.get("confidence", 0.5))
            except Exception:
                conf = 0.5
            conf = max(0.0, min(1.0, conf))
            reasoning = str(item.get("reasoning") or "")[:500]
            mappings.append(ProposedMapping(
                column_name=col_name,
                domain=domain,
                entity=entity,
                attribute=attribute,
                confidence=conf,
                reasoning=reasoning,
            ))

        # If the LLM missed any columns, fall back to heuristics for those only.
        mapped_cols = {m.column_name for m in mappings}
        for col in asset.columns:
            if col.name in mapped_cols:
                continue
            mappings.append(_heuristic_column(asset, col, domain, entity))

        return AssetProposal(
            asset=asset,
            domain=domain,
            entity=entity,
            columns=mappings,
            model_version=model_version,
        )

    # ------------------------------------------------------------------
    # Heuristic fallback — used when LLM is unavailable or errors
    # ------------------------------------------------------------------
    def _heuristic_fallback(self, asset: CrawledAsset, reason: str) -> AssetProposal:
        domain, entity = _heuristic_entity(asset)
        mappings = [_heuristic_column(asset, c, domain, entity) for c in asset.columns]
        return AssetProposal(
            asset=asset,
            domain=domain,
            entity=entity,
            columns=mappings,
            model_version=f"heuristic ({reason})",
        )


# ---------------------------------------------------------------------------
# Stand-alone heuristic helpers
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "You are a data catalog expert who maps physical database columns to "
    "business-domain entities and attributes. Reply with valid JSON only."
)

_DOMAIN_HINTS = {
    "loan": "Servicing",
    "payment": "Servicing",
    "default": "Servicing",
    "foreclosure": "Servicing",
    "bankruptcy": "Servicing",
    "early_resolution": "Servicing",
    "investor": "Servicing",
    "reds": "Servicing",
    "risk": "Servicing",
    "application": "Origination",
    "underwriting": "Origination",
    "disclosure": "Origination",
    "closing": "Origination",
    "lender": "Origination",
    "purchase": "Origination",
    "due_diligence": "Origination",
    "sales": "Sales",
    "commission": "Sales",
    "pipeline": "Sales",
    "officer": "Sales",
    "lead": "Marketing",
    "campaign": "Marketing",
    "attribution": "Marketing",
    "cmh": "Chase My Home",
    "explore": "Chase My Home",
    "buy": "Chase My Home",
    "manage": "Chase My Home",
}


def _heuristic_entity(asset: CrawledAsset) -> tuple:
    name = asset.asset_name.lower()
    domain = "General"
    for token, d in _DOMAIN_HINTS.items():
        if token in name:
            domain = d
            break
    # Entity = singularized table name, title-cased
    entity = name.rstrip("s").replace("_", " ").title().replace(" ", "")
    return domain, entity or asset.asset_name


def _heuristic_column(
    asset: CrawledAsset,
    col: CrawledColumn,
    domain: str,
    entity: str,
) -> ProposedMapping:
    # Strip common id/fk suffixes for attribute name
    attr = col.name
    return ProposedMapping(
        column_name=col.name,
        domain=domain,
        entity=entity,
        attribute=attr,
        confidence=0.35,  # low — we're guessing
        reasoning="heuristic: table-name-based fallback",
    )
