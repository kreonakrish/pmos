"""LLM provider abstraction — same multi-provider pattern as the orchestrator.

Pared down to ``complete()`` only since the translator pipeline does not need
tool-use yet. Keep behaviour identical across providers for easy A/B switching
via the ``LLM_PROVIDER`` env var.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from app.config import settings
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
        """Lightweight connectivity probe. Returns True if at least one provider
        has credentials configured. Does NOT call the API to avoid spend."""
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
    ) -> str:
        model = model or settings.llm_model
        temperature = temperature if temperature is not None else settings.llm_temperature
        max_tokens = max_tokens or settings.llm_max_tokens
        provider = provider or _detect_provider(model)

        async with self._semaphore:
            start = time.monotonic()
            try:
                content = await self._dispatch(provider, messages, model, temperature, max_tokens, trace_id)
                elapsed = time.monotonic() - start
                logger.info(
                    "LLM call completed",
                    layer="adapter",
                    model=model,
                    provider=provider,
                    duration_ms=int(elapsed * 1000),
                    trace_id=trace_id,
                )
                return content
            except Exception as exc:
                elapsed = time.monotonic() - start
                logger.error(
                    "LLM call failed",
                    layer="adapter",
                    model=model,
                    provider=provider,
                    error=str(exc),
                    duration_ms=int(elapsed * 1000),
                    trace_id=trace_id,
                )
                raise

    async def _dispatch(self, provider, messages, model, temperature, max_tokens, trace_id) -> str:
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
    async def _openai_complete(self, messages, model, temperature, max_tokens) -> str:
        client = self._get_openai()
        response = await client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def _anthropic_complete(self, messages, model, temperature, max_tokens) -> str:
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
        return "\n".join(text_parts)

    async def _google_complete(self, messages, model, temperature, max_tokens) -> str:
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
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        return ""

    async def _ollama_complete(self, messages, model, temperature, max_tokens) -> str:
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
        return data.get("message", {}).get("content", "")
