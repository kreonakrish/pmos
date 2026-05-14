"""HTTP adapter for the Translator service.

Calls POST /v1/translate and returns the structured TranslationResult. The
adapter is forgiving — any failure (network, timeout, malformed JSON) returns
an empty translation result so the pipeline can fall back to the bare
decomposition prompt without raising.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.utils.logger import logger


class TranslatorAdapter:
    def __init__(self, base_url: str = "", timeout: float = 0.0) -> None:
        self._base_url = (base_url or settings.translator_service_url).rstrip("/")
        self._timeout = timeout or settings.translator_timeout_sec

    async def translate(
        self,
        question: str,
        team_id: str = "",
        conversation_id: str = "",
        trace_id: str = "",
        prior_turns: Optional[List[Dict[str, Any]]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Phase F7: ``prior_turns`` is forwarded verbatim. Defaults to []."""
        # FinOps: pull user_id from per-task context if the caller didn't pass one.
        if user_id is None:
            try:
                from app.services.finops_context import finops_attribution
                user_id = finops_attribution().get("user_id")
            except Exception:
                user_id = None

        url = f"{self._base_url}/v1/translate"
        payload: Dict[str, Any] = {
            "question": question,
            "team_id": team_id,
            "conversation_id": conversation_id,
            "trace_id": trace_id,
            "prior_turns": list(prior_turns or []),
            "user_id": user_id,
        }
        headers = {"x-request-id": trace_id} if trace_id else {}

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.warning(
                "Translator call failed; returning empty result",
                layer="adapter",
                trace_id=trace_id,
                error=str(exc),
                target=url,
            )
            return _empty_result(trace_id)

        if not isinstance(data, dict):
            logger.warning(
                "Translator returned non-dict payload",
                layer="adapter", trace_id=trace_id,
            )
            return _empty_result(trace_id)

        return data

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/health")
                return resp.status_code == 200
        except Exception:
            return False


def _empty_result(trace_id: str) -> Dict[str, Any]:
    return {
        "intent": "unknown",
        "domain": None,
        "canonical_entities": [],
        "relationships": [],
        "dataset_bindings": [],
        "domain_subtasks": [],
        "used_ontology_subgraph": {"nodes": [], "edges": []},
        "ontology_versions": [],
        "fallback_used": True,
        "trace_id": trace_id,
    }
