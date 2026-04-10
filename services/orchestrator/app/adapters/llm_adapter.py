"""LLM provider abstraction with multi-provider support, concurrency limiting, and observability."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.utils.logger import logger
from app.utils.telemetry import LLM_CALL_TOTAL, LLM_LATENCY


def _detect_provider(model: str) -> str:
    """Infer provider from model name if not explicitly given."""
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
        self._anthropic_client: Optional[Any] = None

    def _get_openai(self) -> AsyncOpenAI:
        if self._openai is None:
            self._openai = AsyncOpenAI(api_key=settings.openai_api_key)
        return self._openai

    # ------------------------------------------------------------------
    # Simple text completion (backward compatible)
    # ------------------------------------------------------------------
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
                content = await self._dispatch_complete(provider, messages, model, temperature, max_tokens, trace_id)
                elapsed = time.monotonic() - start
                LLM_CALL_TOTAL.labels(model=model, status="success").inc()
                LLM_LATENCY.labels(model=model).observe(elapsed)
                logger.info("LLM call completed", layer="adapter", model=model, provider=provider,
                            duration_ms=int(elapsed * 1000), trace_id=trace_id)
                return content
            except Exception as exc:
                elapsed = time.monotonic() - start
                LLM_CALL_TOTAL.labels(model=model, status="error").inc()
                logger.error("LLM call failed", layer="adapter", model=model, provider=provider,
                             error=str(exc), duration_ms=int(elapsed * 1000), trace_id=trace_id)
                raise

    async def _dispatch_complete(self, provider: str, messages, model, temperature, max_tokens, trace_id) -> str:
        if provider == "openai":
            return await self._openai_complete(messages, model, temperature, max_tokens)
        elif provider == "anthropic":
            return await self._anthropic_complete(messages, model, temperature, max_tokens, trace_id)
        elif provider == "google":
            return await self._google_complete(messages, model, temperature, max_tokens, trace_id)
        elif provider == "ollama":
            return await self._ollama_complete(messages, model, temperature, max_tokens)
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    # ------------------------------------------------------------------
    # Tool-use capable completion (returns full message structure)
    # ------------------------------------------------------------------
    async def complete_with_tools(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        trace_id: str = "",
        provider: Optional[str] = None,
    ) -> Dict[str, Any]:
        model = model or settings.llm_model
        temperature = temperature if temperature is not None else settings.llm_temperature
        max_tokens = max_tokens or settings.llm_max_tokens
        provider = provider or _detect_provider(model)

        async with self._semaphore:
            start = time.monotonic()
            try:
                if provider == "openai":
                    result = await self._openai_complete_with_tools(messages, tools, model, temperature, max_tokens)
                elif provider == "anthropic":
                    result = await self._anthropic_complete_with_tools(messages, tools, model, temperature, max_tokens, trace_id)
                elif provider == "google":
                    # Google doesn't have native function calling via our simple adapter — fall back to text
                    content = await self._google_complete(messages, model, temperature, max_tokens, trace_id)
                    result = {"content": content, "tool_calls": None, "finish_reason": "stop", "usage": None}
                elif provider == "ollama":
                    content = await self._ollama_complete(messages, model, temperature, max_tokens)
                    result = {"content": content, "tool_calls": None, "finish_reason": "stop", "usage": None}
                else:
                    raise ValueError(f"Unsupported LLM provider: {provider}")

                elapsed = time.monotonic() - start
                LLM_CALL_TOTAL.labels(model=model, status="success").inc()
                LLM_LATENCY.labels(model=model).observe(elapsed)
                logger.info("LLM tool call completed", layer="adapter", model=model, provider=provider,
                            duration_ms=int(elapsed * 1000), finish_reason=result.get("finish_reason"),
                            has_tool_calls=bool(result.get("tool_calls")), trace_id=trace_id)
                return result
            except Exception as exc:
                elapsed = time.monotonic() - start
                LLM_CALL_TOTAL.labels(model=model, status="error").inc()
                logger.error("LLM tool call failed", layer="adapter", model=model, provider=provider,
                             error=str(exc), duration_ms=int(elapsed * 1000), trace_id=trace_id)
                raise

    # ==================================================================
    # OpenAI
    # ==================================================================
    async def _openai_complete(self, messages, model, temperature, max_tokens) -> str:
        client = self._get_openai()
        response = await client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    async def _openai_complete_with_tools(self, messages, tools, model, temperature, max_tokens) -> Dict[str, Any]:
        client = self._get_openai()
        kwargs: Dict[str, Any] = {
            "model": model, "messages": messages,
            "temperature": temperature, "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        usage = response.usage

        result: Dict[str, Any] = {
            "content": choice.message.content or "",
            "tool_calls": None,
            "finish_reason": choice.finish_reason,
            "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens,
                      "total_tokens": usage.total_tokens} if usage else None,
        }

        if choice.message.tool_calls:
            result["tool_calls"] = [
                {"id": tc.id, "type": tc.type,
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in choice.message.tool_calls
            ]
            result["assistant_message"] = {
                "role": "assistant", "content": choice.message.content,
                "tool_calls": result["tool_calls"],
            }
        return result

    # ==================================================================
    # Anthropic
    # ==================================================================
    async def _anthropic_complete(self, messages, model, temperature, max_tokens, trace_id="") -> str:
        api_key = settings.anthropic_api_key
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured. Set it in .env to use Anthropic models.")

        # Separate system message from user/assistant messages
        system_text = ""
        api_messages = []
        for m in messages:
            if m["role"] == "system":
                system_text += m["content"] + "\n"
            else:
                api_messages.append({"role": m["role"], "content": m["content"]})

        if not api_messages:
            api_messages = [{"role": "user", "content": "Hello"}]

        payload: Dict[str, Any] = {
            "model": model, "max_tokens": max_tokens,
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

        # Extract text from content blocks
        text_parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        return "\n".join(text_parts)

    async def _anthropic_complete_with_tools(self, messages, tools, model, temperature, max_tokens, trace_id="") -> Dict[str, Any]:
        api_key = settings.anthropic_api_key
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured. Set it in .env to use Anthropic models.")

        system_text = ""
        api_messages = []
        for m in messages:
            if m.get("role") == "system":
                system_text += m["content"] + "\n"
            elif m.get("role") == "tool":
                # Convert OpenAI tool result format to Anthropic format
                api_messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": m.get("tool_call_id", ""), "content": m.get("content", "")}],
                })
            elif m.get("role") == "assistant" and m.get("tool_calls"):
                # Convert OpenAI assistant tool_calls to Anthropic format
                content_blocks = []
                if m.get("content"):
                    content_blocks.append({"type": "text", "text": m["content"]})
                for tc in m["tool_calls"]:
                    try:
                        args = json.loads(tc["function"]["arguments"]) if isinstance(tc["function"]["arguments"], str) else tc["function"]["arguments"]
                    except json.JSONDecodeError:
                        args = {}
                    content_blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["function"]["name"], "input": args})
                api_messages.append({"role": "assistant", "content": content_blocks})
            else:
                api_messages.append({"role": m.get("role", "user"), "content": m.get("content", "")})

        if not api_messages:
            api_messages = [{"role": "user", "content": "Hello"}]

        # Convert OpenAI tools to Anthropic format
        anthropic_tools = []
        if tools:
            for t in tools:
                func = t.get("function", {})
                anthropic_tools.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {"type": "object", "properties": {}}),
                })

        payload: Dict[str, Any] = {
            "model": model, "max_tokens": max_tokens, "messages": api_messages,
        }
        if system_text.strip():
            payload["system"] = system_text.strip()
        if temperature is not None:
            payload["temperature"] = temperature
        if anthropic_tools:
            payload["tools"] = anthropic_tools

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

        # Parse response
        content_text = ""
        tool_calls_list = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block["text"]
            elif block.get("type") == "tool_use":
                tool_calls_list.append({
                    "id": block["id"],
                    "type": "function",
                    "function": {"name": block["name"], "arguments": json.dumps(block.get("input", {}))},
                })

        usage = data.get("usage", {})
        result: Dict[str, Any] = {
            "content": content_text,
            "tool_calls": tool_calls_list if tool_calls_list else None,
            "finish_reason": "tool_calls" if tool_calls_list else data.get("stop_reason", "end_turn"),
            "usage": {
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
                "total_tokens": usage.get("input_tokens", 0) + usage.get("output_tokens", 0),
            },
        }

        if tool_calls_list:
            result["assistant_message"] = {
                "role": "assistant", "content": content_text,
                "tool_calls": tool_calls_list,
            }

        return result

    # ==================================================================
    # Google (Gemini via REST API)
    # ==================================================================
    async def _google_complete(self, messages, model, temperature, max_tokens, trace_id="") -> str:
        api_key = settings.google_api_key
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not configured. Set it in .env to use Google models.")

        # Convert messages to Gemini format
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

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        candidates = data.get("candidates", [])
        if candidates:
            parts = candidates[0].get("content", {}).get("parts", [])
            return "".join(p.get("text", "") for p in parts)
        return ""

    # ==================================================================
    # Ollama (local, OpenAI-compatible API)
    # ==================================================================
    async def _ollama_complete(self, messages, model, temperature, max_tokens) -> str:
        base_url = settings.ollama_base_url.rstrip("/")
        payload = {
            "model": model, "messages": messages,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data.get("message", {}).get("content", "")
