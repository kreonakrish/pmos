"""LLM adapter — provider-agnostic interface backed by OpenAI by default.

Token usage is recorded to pmos.llm_call_log via cost_recorder for the
Financial Governance UI. Recording is fire-and-forget — never blocks the
LLM response."""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Optional

import openai

from app.config import settings
from app.services.cost_recorder import record_llm_call
from app.utils.logger import get_logger

logger = get_logger(layer="adapter")


def _safe_record(**kwargs) -> None:
    try:
        asyncio.create_task(record_llm_call(**kwargs))
    except Exception:
        pass


class LLMAdapter(ABC):
    """Abstract LLM interface — swap provider via config."""

    @abstractmethod
    async def complete(
        self, prompt: str, system: str = "",
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> str:
        """Return the model's text completion."""

    @abstractmethod
    async def complete_json(
        self, prompt: str, system: str = "",
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Return a parsed JSON object from the model."""


class OpenAIAdapter(LLMAdapter):
    """OpenAI / Azure-compatible LLM adapter."""

    def __init__(self) -> None:
        self._client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.llm_model

    async def complete(
        self, prompt: str, system: str = "",
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> str:
        t0 = time.monotonic()
        call_trace = trace_id or str(uuid.uuid4())
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,  # type: ignore[arg-type]
                temperature=0.2,
            )
            text = response.choices[0].message.content or ""
            duration_ms = int((time.monotonic() - t0) * 1000)
            usage = response.usage
            logger.info(
                "llm_call_completed",
                trace_id=call_trace,
                model=self._model,
                duration_ms=duration_ms,
                tokens_used=usage.total_tokens if usage else None,
            )
            _safe_record(
                service_name="meta-assembly", provider="openai",
                model=self._model,
                prompt_tokens=usage.prompt_tokens if usage else 0,
                completion_tokens=usage.completion_tokens if usage else 0,
                trace_id=call_trace, conversation_id=conversation_id,
                user_id=user_id, team_id=team_id, agent_id=agent_id,
                latency_ms=duration_ms, finish_reason="stop",
            )
            return text
        except Exception as exc:
            duration_ms = int((time.monotonic() - t0) * 1000)
            logger.error(
                "llm_call_failed",
                trace_id=call_trace,
                model=self._model,
                duration_ms=duration_ms,
                error=str(exc),
            )
            _safe_record(
                service_name="meta-assembly", provider="openai",
                model=self._model, prompt_tokens=0, completion_tokens=0,
                trace_id=call_trace, conversation_id=conversation_id,
                user_id=user_id, team_id=team_id, agent_id=agent_id,
                latency_ms=duration_ms, error=str(exc),
            )
            raise

    async def complete_json(
        self, prompt: str, system: str = "",
        trace_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Request JSON-formatted output and parse it."""
        json_system = (system + "\n\n" if system else "") + (
            "You MUST respond with valid JSON only. No markdown, no code fences, no explanation."
        )
        raw = await self.complete(
            prompt, system=json_system, trace_id=trace_id,
            conversation_id=conversation_id, user_id=user_id,
            team_id=team_id, agent_id=agent_id,
        )

        # Strip code fences if model still wraps
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            logger.error("llm_json_parse_failed", error=str(exc), raw_snippet=raw[:300])
            raise ValueError(f"LLM did not return valid JSON: {exc}") from exc


def get_llm_adapter() -> LLMAdapter:
    provider = settings.llm_provider.lower()
    if provider == "openai":
        return OpenAIAdapter()
    raise ValueError(f"Unsupported LLM provider: {provider}")
