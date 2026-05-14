"""LLM provider abstraction — same multi-provider pattern as the orchestrator.

Pared down to ``complete()`` only since the translator pipeline does not need
tool-use yet. Keep behaviour identical across providers for easy A/B switching
via the ``LLM_PROVIDER`` env var.

Token usage and cost are recorded to the shared pmos.llm_call_log table via
``services.cost_recorder.record_llm_call`` (Financial Governance) — fire and
forget so the LLM response path is never blocked.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.services.cost_recorder import record_llm_call
from app.services.finops_context import finops_attribution
from app.utils.logger import logger


def _detect_provider(model: str) -> str:
    m = model.lower()
    if m.startswith("gpt-") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4"):
        return "openai"
    if m.startswith("claude-"):
        return "anthropic"
    if m.startswith("gemini-"):
        return "google"
    if m in ("llama3", "mistral", "codellama", "mixtral") or m.startswith("llama"):
        return "ollama"
    return settings.llm_provider


def _safe_record(**kwargs) -> None:
    try:
        asyncio.create_task(record_llm_call(**kwargs))
    except Exception:
        pass


def _resolve_attribution(
    trace_id: str,
    conversation_id: Optional[str],
    user_id: Optional[str],
    team_id: Optional[str],
    agent_id: Optional[str],
    tool_invocation_id: Optional[str],
) -> Dict[str, Any]:
    """Caller kwargs win; fall back to per-task FinOps context for any
    field the caller didn't supply."""
    ctx = finops_attribution()
    return {
        "trace_id": trace_id or ctx.get("trace_id"),
        "conversation_id": conversation_id if conversation_id is not None else ctx.get("conversation_id"),
        "user_id": user_id if user_id is not None else ctx.get("user_id"),
        "team_id": team_id if team_id is not None else ctx.get("team_id"),
        "agent_id": agent_id if agent_id is not None else ctx.get("agent_id"),
        "tool_invocation_id": tool_invocation_id,
    }


class LLMAdapter:
    """Provider-agnostic async LLM client bounded by MAX_CONCURRENT_LLM_CALLS."""

    def __init__(self) -> None:
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_llm_calls)
        self._openai: Optional[AsyncOpenAI] = None

    def _get_openai(self) -> AsyncOpenAI:
        if self._openai is None:
            self._openai = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._openai

    async def health_check(self) -> bool:
        return bool(
            settings.openai_api_key
            or settings.anthropic_api_key
            or settings.google_api_key
        )

    async def complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        trace_id: str = "",
        provider: Optional[str] = None,
        # Financial Governance attribution (all optional)
        conversation_id: Optional[str] = None,
        user_id: Optional[str] = None,
        team_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        tool_invocation_id: Optional[str] = None,
    ) -> str:
        model = model or settings.llm_model
        temperature = temperature if temperature is not None else settings.llm_temperature
        max_tokens = max_tokens or settings.llm_max_tokens
        provider = provider or _detect_provider(model)

        async with self._semaphore:
            start = time.monotonic()
            try:
                content, usage = await self._dispatch(provider, messages, model, temperature, max_tokens, trace_id)
                elapsed = time.monotonic() - start
                logger.info(
                    "LLM call completed", layer="adapter", model=model, provider=provider,
                    duration_ms=int(elapsed * 1000), trace_id=trace_id,
                )
                attrib = _resolve_attribution(trace_id, conversation_id, user_id, team_id, agent_id, tool_invocation_id)
                _safe_record(
                    service_name="translator", provider=provider, model=model,
                    prompt_tokens=(usage or {}).get("prompt_tokens", 0),
                    completion_tokens=(usage or {}).get("completion_tokens", 0),
                    latency_ms=int(elapsed * 1000), finish_reason="stop",
                    **attrib,
                )
                return content
            except Exception as exc:
                elapsed = time.monotonic() - start
                logger.error(
                    "LLM call failed", layer="adapter", model=model, provider=provider,
                    error=str(exc), duration_ms=int(elapsed * 1000), trace_id=trace_id,
                )
                attrib = _resolve_attribution(trace_id, conversation_id, user_id, team_id, agent_id, tool_invocation_id)
                _safe_record(
                    service_name="translator", provider=provider, model=model,
                    prompt_tokens=0, completion_tokens=0,
                    latency_ms=int(elapsed * 1000), error=str(exc),
                    **attrib,
                )
                raise

    async def _dispatch(self, provider, messages, model, temperature, max_tokens, trace_id):
        """Returns (content, usage_dict)."""
        if provider == "openai":
            return await self._openai_complete(messages, model, temperature, max_tokens)
        if provider == "anthropic":
            return await self._anthropic_complete(messages, model, temperature, max_tokens)
        if provider == "google":
            return await self._google_complete(messages, model, temperature, max_tokens)
        if provider == "ollama":
            return await self._ollama_complete(messages, model, temperature, max_tokens)
        raise ValueError(f"Unsupported LLM provider: {provider}")

    # ------------------------------------------------------------------
    async def _openai_complete(self, messages, model, temperature, max_tokens):
        client = self._get_openai()
        response = await client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
        usage = response.usage
        usage_dict = {
            "prompt_tokens": usage.prompt_tokens,
            "completion_tokens": usage.completion_tokens,
            "total_tokens": usage.total_tokens,
        } if usage else None
        return (response.choices[0].message.content or ""), usage_dict

    async def _anthropic_complete(self, messages, model, temperature, max_tokens):
        api_key = settings.anthropic_api_key
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured.")
        system_text = ""
        api_messages: List[Dict[str, Any]] = []
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            else:
                api_messages.append({"role": m["role"], "content": m["content"]})
        if not api_messages:
            api_messages = [{"role": "user", "content": "Hello"}]
        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": api_messages,
        }
        if system_text.strip():
            payload["system"] = system_text.strip()
        if temperature is not None:
            payload["temperature"] = temperature
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        usage_raw = data.get("usage", {}) or {}
        usage_dict = {
            "prompt_tokens": int(usage_raw.get("input_tokens", 0)),
            "completion_tokens": int(usage_raw.get("output_tokens", 0)),
            "total_tokens": int(usage_raw.get("input_tokens", 0)) + int(usage_raw.get("output_tokens", 0)),
        }
        return "\n".join(text_parts), usage_dict

    async def _google_complete(self, messages, model, temperature, max_tokens):
        api_key = settings.google_api_key
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not configured.")
        contents = []
        system_instruction = ""
        for m in messages:
            if m["role"] == "system":
                system_instruction += m["content"] + "\n"
            else:
                role = "model" if m["role"] == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": m["content"]}]})
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system_instruction.strip():
            payload["systemInstruction"] = {"parts": [{"text": system_instruction.strip()}]}
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={api_key}"
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        candidates = data.get("candidates", [])
        usage_raw = data.get("usageMetadata", {}) or {}
        usage_dict = {
            "prompt_tokens": int(usage_raw.get("promptTokenCount", 0)),
            "completion_tokens": int(usage_raw.get("candidatesTokenCount", 0)),
            "total_tokens": int(usage_raw.get("totalTokenCount", 0)),
        }
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts), usage_dict
        return "", usage_dict

    async def _ollama_complete(self, messages, model, temperature, max_tokens):
        base_url = settings.ollama_base_url.rstrip("/")
        payload = {
            "model": model,
            "messages": messages,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        prompt_tokens = int(data.get("prompt_eval_count", 0))
        completion_tokens = int(data.get("eval_count", 0))
        usage_dict = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        return data.get("message", {}).get("content", ""), usage_dict
