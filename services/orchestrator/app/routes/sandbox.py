"""Sandboxed execution endpoints for tool testing and LLM chat.

POST /v1/sandbox/execute-python
POST /v1/sandbox/chat-completion
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.adapters.llm_adapter import LLMAdapter
from app.config import settings
from app.services import blackboard, budget
from app.utils.events import events
from app.utils.logger import logger


# ---------------------------------------------------------------------------
# Phase A.3 helpers — per-iteration memory refresh
# ---------------------------------------------------------------------------

# Captures plausible entity strings inside tool results: identifiers, snake/dot
# separated names, capitalized phrases. Intentionally permissive — the LLM is
# the final consumer and can ignore noise.
_ENTITY_RE = re.compile(
    r"\b("
    r"[A-Z][A-Z0-9_]{2,}"             # SCREAMING_SNAKE
    r"|[A-Z][a-z]+(?:[A-Z][a-z]+)+"    # CamelCase
    r"|[a-z][a-z0-9]*(?:[._][a-z][a-z0-9]*)+"  # snake.dotted
    r")\b"
)


def _extract_entities(text: str, *, limit: int = 12) -> List[str]:
    """Pull entity-like tokens from a string, deduped, capped."""
    if not text or not isinstance(text, str):
        return []
    seen: List[str] = []
    seen_set: set = set()
    for m in _ENTITY_RE.finditer(text[:8000]):  # cap scan range for cost
        tok = m.group(1)
        if len(tok) < 3 or len(tok) > 80:
            continue
        if tok.lower() in seen_set:
            continue
        seen_set.add(tok.lower())
        seen.append(tok)
        if len(seen) >= limit:
            break
    return seen


async def _memory_refresh(
    *,
    agent_id: Optional[int],
    entities: List[str],
    trace_id: str,
) -> str:
    """Best-effort: ask memory service for episodic context related to the new
    entities discovered in this iteration. Returns a compact context string,
    or "" if nothing useful (or memory unavailable).
    """
    if not entities or not agent_id:
        return ""
    query = " ".join(entities[:6])
    try:
        url = f"{settings.memory_service_url}/v1/memory/retrieve"
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(
                url,
                params={
                    "agent_id": int(agent_id),
                    "tier": "episodic",
                    "query": query,
                    "k": 3,
                },
                headers={"x-request-id": trace_id or ""},
            )
            if resp.status_code != 200:
                return ""
            data = resp.json()
    except Exception:
        return ""

    results = data.get("results") or []
    if not results:
        return ""

    lines = ["[MEMORY REFRESH — episodic findings related to entities you just discovered]"]
    for r in results[:3]:
        content = r.get("content") or r.get("summary") or ""
        if not content:
            continue
        if len(content) > 320:
            content = content[:320] + "…"
        lines.append(f"- {content}")
    if len(lines) == 1:  # only the header
        return ""
    lines.append("[END MEMORY REFRESH]")
    return "\n".join(lines)

router = APIRouter(prefix="/v1/sandbox", tags=["sandbox"])

ALLOWED_IMPORTS = {
    "json", "re", "math", "datetime", "collections", "itertools", "functools",
    "statistics", "csv", "string", "textwrap", "decimal", "fractions",
    "random", "hashlib", "base64", "urllib.parse", "copy",
}

SANDBOX_TIMEOUT = 30


class PythonExecRequest(BaseModel):
    code: str
    inputs: Dict[str, Any] = {}
    timeout: int = SANDBOX_TIMEOUT


class PythonExecResponse(BaseModel):
    success: bool
    output: Any = None
    error: str | None = None
    latency_ms: int = 0
    trace_id: str = ""


@router.post("/execute-python", response_model=PythonExecResponse)
async def execute_python(body: PythonExecRequest, request: Request) -> PythonExecResponse:
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.monotonic()

    logger.info(
        "Python sandbox execution requested",
        layer="router",
        trace_id=trace_id,
        code_length=len(body.code),
    )

    # Build the wrapper script
    wrapper = f"""
import json, sys

{body.code}

try:
    _inputs = json.loads(sys.argv[1])
    _result = execute(_inputs)
    print(json.dumps(_result, default=str))
except Exception as _e:
    print(json.dumps({{"error": str(_e)}}))
    sys.exit(1)
"""

    inputs_json = json.dumps(body.inputs)
    timeout = min(body.timeout, SANDBOX_TIMEOUT)

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", "-c", wrapper, inputs_json,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            elapsed = int((time.monotonic() - start) * 1000)
            logger.warn(
                "Python sandbox timed out",
                layer="router",
                trace_id=trace_id,
                timeout=timeout,
            )
            return PythonExecResponse(
                success=False,
                error=f"Execution timed out after {timeout}s",
                latency_ms=elapsed,
                trace_id=trace_id,
            )

        elapsed = int((time.monotonic() - start) * 1000)
        stdout_str = stdout.decode("utf-8", errors="replace").strip()
        stderr_str = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            error_msg = stderr_str or stdout_str or f"Process exited with code {proc.returncode}"
            logger.error(
                "Python sandbox execution failed",
                layer="router",
                trace_id=trace_id,
                error=error_msg,
                latency_ms=elapsed,
            )
            return PythonExecResponse(
                success=False,
                error=error_msg,
                latency_ms=elapsed,
                trace_id=trace_id,
            )

        # Parse JSON output
        try:
            parsed = json.loads(stdout_str)
            if isinstance(parsed, dict) and "error" in parsed and len(parsed) == 1:
                return PythonExecResponse(
                    success=False,
                    error=parsed["error"],
                    latency_ms=elapsed,
                    trace_id=trace_id,
                )
            return PythonExecResponse(
                success=True,
                output=parsed,
                latency_ms=elapsed,
                trace_id=trace_id,
            )
        except json.JSONDecodeError:
            return PythonExecResponse(
                success=True,
                output={"stdout": stdout_str, "stderr": stderr_str or None},
                latency_ms=elapsed,
                trace_id=trace_id,
            )

    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.error(
            "Python sandbox unexpected error",
            layer="router",
            trace_id=trace_id,
            error=str(exc),
        )
        return PythonExecResponse(
            success=False,
            error=str(exc),
            latency_ms=elapsed,
            trace_id=trace_id,
        )


# ---------------------------------------------------------------------------
# Chat Completion endpoint
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    messages: List[ChatMessage]
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class ChatCompletionResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    model: Optional[str] = None
    latency_ms: int = 0
    tokens_used: Optional[int] = None
    error: Optional[str] = None
    trace_id: str = ""


# Module-level LLM adapter instance (reused across requests)
_llm_adapter = LLMAdapter()


@router.post("/chat-completion", response_model=ChatCompletionResponse)
async def chat_completion(body: ChatCompletionRequest, request: Request) -> ChatCompletionResponse:
    """Proxy a chat completion request through the orchestrator's LLM adapter."""
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.monotonic()

    logger.info(
        "Chat completion requested",
        layer="router",
        trace_id=trace_id,
        message_count=len(body.messages),
        model=body.model,
    )

    try:
        messages = [{"role": m.role, "content": m.content} for m in body.messages]

        content = await _llm_adapter.complete(
            messages=messages,
            model=body.model,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            trace_id=trace_id,
        )

        elapsed = int((time.monotonic() - start) * 1000)

        logger.info(
            "Chat completion succeeded",
            layer="router",
            trace_id=trace_id,
            latency_ms=elapsed,
            model=body.model,
        )

        return ChatCompletionResponse(
            success=True,
            response=content,
            model=body.model or "default",
            latency_ms=elapsed,
            tokens_used=None,  # OpenAI usage info not exposed by current adapter
            trace_id=trace_id,
        )

    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.error(
            "Chat completion failed",
            layer="router",
            trace_id=trace_id,
            error=str(exc),
            latency_ms=elapsed,
        )
        return ChatCompletionResponse(
            success=False,
            error=str(exc),
            latency_ms=elapsed,
            trace_id=trace_id,
        )


# ---------------------------------------------------------------------------
# Agent Execute endpoint — agentic tool-use loop
# ---------------------------------------------------------------------------

class ToolDefinition(BaseModel):
    name: str
    description: str
    tool_type: str
    tool_id: str
    config: Dict[str, Any] = {}

class AgentExecuteRequest(BaseModel):
    messages: List[ChatMessage]
    tools: List[ToolDefinition] = []
    tool_executor_url: str = ""  # URL to POST tool executions to
    provider: Optional[str] = None  # openai, anthropic, google, ollama
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    max_iterations: int = 5
    max_continuations: int = 3  # max auto-continues for truncated responses
    # Sub-agent spawning context
    team_id: Optional[str] = None
    graph_id: Optional[str] = None
    parent_node_id: Optional[str] = None
    current_depth: int = 0
    max_sub_agent_depth: int = 3
    conversation_id: Optional[str] = None
    # Phase A: identity for the executing agent. Used for blackboard authorship
    # filtering (so an agent doesn't read its own publishes back) and for
    # per-iteration memory refresh against the agent's tier. Optional so legacy
    # callers (e.g., direct sandbox tests) keep working.
    agent_id: Optional[int] = None
    agent_name: Optional[str] = None
    node_id: Optional[str] = None
    iteration_round: int = 0  # outer-loop round (Phase A.4); sandbox just echoes it

class ToolCallRecord(BaseModel):
    tool_name: str
    tool_type: str
    tool_id: str
    arguments: Dict[str, Any]
    result: Any = None
    success: bool = True
    latency_ms: int = 0
    is_sub_agent: bool = False
    sub_agent_id: Optional[str] = None
    sub_agent_name: Optional[str] = None
    sub_agent_depth: int = 0

class AgentExecuteResponse(BaseModel):
    success: bool
    response: Optional[str] = None
    model: Optional[str] = None
    latency_ms: int = 0
    tokens_used: Optional[int] = None
    tool_calls: List[ToolCallRecord] = []
    iterations: int = 0
    error: Optional[str] = None
    trace_id: str = ""
    sub_agent_calls: List[Dict[str, Any]] = []


SPAWN_SUB_AGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_sub_agent",
        "description": (
            "Delegate a complex sub-task to a specialist sub-agent. "
            "The sub-agent will be selected via capability negotiation from your team, "
            "work autonomously with its own tools and memory context, and return results. "
            "Use this when a sub-task requires different tools or expertise than you have."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {
                    "type": "string",
                    "description": "Clear, detailed description of the sub-task to delegate",
                },
                "required_capabilities": {
                    "type": "string",
                    "description": "Comma-separated capabilities needed (e.g. 'database,graph,github')",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context or prior findings to pass to the sub-agent",
                },
            },
            "required": ["task_description"],
        },
    },
}


async def _execute_sub_agent(
    parent_body: AgentExecuteRequest,
    task_description: str,
    required_capabilities: str,
    context: str,
    trace_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Spawn a sub-agent: negotiate, create TaskNode, execute recursively, return result."""
    import httpx
    from app.config import settings

    sub_start = time.monotonic()
    neo4j = getattr(request.app.state, "neo4j", None)
    agent_mgmt = getattr(request.app.state, "agent_mgmt", None)
    memory_adapter = getattr(request.app.state, "memory", None)

    new_depth = parent_body.current_depth + 1
    sub_node_id = str(uuid.uuid4())

    logger.info(
        "Sub-agent spawn initiated",
        layer="router",
        trace_id=trace_id,
        depth=new_depth,
        parent_node_id=parent_body.parent_node_id,
        task_description=task_description[:80],
    )

    # 1. Create sub-agent TaskNode in Neo4j
    if neo4j:
        try:
            await neo4j.create_task_node(
                node_id=sub_node_id,
                graph_id=parent_body.graph_id or "",
                parent_id=parent_body.parent_node_id or "",
                description=f"[SUB_AGENT depth={new_depth}] {task_description[:200]}",
                node_type="SUB_AGENT",
                depth=new_depth,
                iteration=0,
                criticality="MEDIUM",
                trace_id=trace_id,
            )
            if parent_body.parent_node_id:
                await neo4j.link_spawned_by(
                    child_id=sub_node_id,
                    parent_id=parent_body.parent_node_id,
                    trace_id=trace_id,
                )
        except Exception as exc:
            logger.warning("Failed to create sub-agent TaskNode", layer="router",
                           error=str(exc), trace_id=trace_id)

    # 2. Select best sub-agent via capability negotiation
    selected_agent_id = None
    selected_agent_name = "default"
    selected_model = parent_body.model
    selected_provider = parent_body.provider
    sub_tools: List[ToolDefinition] = []

    if neo4j and agent_mgmt and parent_body.team_id:
        try:
            from app.services.agent_selector import AgentSelector
            from app.services.capability_negotiation import CapabilityNegotiationService
            from app.adapters.memory_adapter import MemoryAdapter
            from app.models.bid import BidRequest

            selector = AgentSelector(neo4j)
            _, specialists = await selector.select_primary_and_fallbacks(
                team_id=parent_body.team_id, trace_id=trace_id,
            )

            if specialists:
                # Use capability negotiation to pick the best agent
                mem = memory_adapter or MemoryAdapter(settings.memory_service_url)
                neg_svc = CapabilityNegotiationService(
                    neo4j=neo4j, llm=_llm_adapter, memory=mem, agent_mgmt=agent_mgmt,
                )
                bid_req = BidRequest(
                    task_id=sub_node_id,
                    graph_id=parent_body.graph_id or "",
                    task_description=task_description,
                    task_type=required_capabilities or "general",
                    trace_id=trace_id,
                )
                neg_result = await neg_svc.negotiate(
                    bid_request=bid_req, team_agents=specialists, trace_id=trace_id,
                )
                if neg_result.winner:
                    selected_agent_id = neg_result.winner.agent_id
                    selected_agent_name = neg_result.winner.agent_name
                    selected_model = neg_result.winner.foundation_model or parent_body.model
                    from app.adapters.llm_adapter import _detect_provider
                    selected_provider = _detect_provider(selected_model)

            # 3. Fetch sub-agent tools
            if selected_agent_id:
                try:
                    raw_tools = await agent_mgmt.get_agent_tools(
                        agent_id=selected_agent_id, trace_id=trace_id,
                    )
                    # Phase C.4: parse required_capabilities into a hint
                    # set used for tool scoping. Empty / "general" means
                    # no filter — preserves prior behavior.
                    cap_hint = {
                        c.strip().lower()
                        for c in (required_capabilities or "").split(",")
                        if c.strip() and c.strip().lower() != "general"
                    }
                    for t in raw_tools:
                        tool_config: Dict[str, Any] = {}
                        auth_config = t.get("tool_auth_config") or t.get("auth_config")
                        if auth_config and isinstance(auth_config, dict):
                            tool_config.update(auth_config)
                        elif auth_config and isinstance(auth_config, str):
                            try:
                                tool_config.update(json.loads(auth_config))
                            except (json.JSONDecodeError, TypeError):
                                pass
                        endpoint = t.get("tool_endpoint") or t.get("endpoint") or ""
                        tool_type = t.get("tool_type", "GENERIC")
                        if endpoint:
                            tool_config["endpoint"] = endpoint
                            if tool_type == "DATABASE":
                                tool_config["connection_string"] = endpoint
                            elif tool_type == "GRAPH":
                                tool_config["connection_string"] = endpoint
                                tool_config["uri"] = endpoint
                            elif tool_type == "API":
                                tool_config["base_url"] = endpoint

                        # Phase C.4: per-sub-task tool filter. When the
                        # spawn call named specific capabilities (e.g.
                        # "database,graph"), only inject tools whose
                        # type/name overlaps. Cuts prompt bloat AND
                        # narrows the bid space if the sub-agent loops.
                        if cap_hint:
                            tname = (t.get("tool_name") or t.get("name", "")).lower()
                            ttype = (tool_type or "").lower()
                            tdesc = (t.get("tool_description") or t.get("description", "")).lower()
                            matches = (
                                ttype in cap_hint
                                or any(c in tname for c in cap_hint)
                                or any(c in tdesc for c in cap_hint)
                            )
                            if not matches:
                                continue

                        sub_tools.append(ToolDefinition(
                            name=t.get("tool_name") or t.get("name", "unknown"),
                            description=t.get("tool_description") or t.get("description", ""),
                            tool_type=tool_type,
                            tool_id=str(t.get("tool_id", "")),
                            config=tool_config,
                        ))
                    if cap_hint and not sub_tools:
                        logger.info(
                            "Sub-agent capability filter eliminated all tools — "
                            "falling back to full roster so the sub-agent isn't tool-less",
                            layer="router",
                            cap_hint=list(cap_hint),
                            trace_id=trace_id,
                        )
                        # Refetch without the filter — prefer running with
                        # too many tools over zero tools.
                        for t in raw_tools:
                            tool_config = {}
                            endpoint = t.get("tool_endpoint") or t.get("endpoint") or ""
                            tool_type = t.get("tool_type", "GENERIC")
                            if endpoint:
                                tool_config["endpoint"] = endpoint
                            sub_tools.append(ToolDefinition(
                                name=t.get("tool_name") or t.get("name", "unknown"),
                                description=t.get("tool_description") or t.get("description", ""),
                                tool_type=tool_type,
                                tool_id=str(t.get("tool_id", "")),
                                config=tool_config,
                            ))
                except Exception as exc:
                    logger.warning("Failed to fetch sub-agent tools", layer="router",
                                   error=str(exc), trace_id=trace_id)
        except Exception as exc:
            logger.warning("Sub-agent negotiation failed, using parent context",
                           layer="router", error=str(exc), trace_id=trace_id)

    # 4. Assemble sub-agent memory context
    system_prompt = (
        f"You are {selected_agent_name}, a specialist sub-agent (depth {new_depth}). "
        f"You have been delegated the following sub-task by a parent agent. "
        f"Complete it thoroughly using your available tools.\n"
    )
    if context:
        system_prompt += f"\nCONTEXT FROM PARENT AGENT:\n{context}\n"

    if memory_adapter and selected_agent_id:
        try:
            agent_id_int = int(selected_agent_id) if selected_agent_id.isdigit() else 0
            # Phase C.4: scope memory retrieval to the sub-task's
            # neighborhood — task_type carries the spawn's required_capabilities,
            # recent_messages includes the parent's context block and the
            # sub-task description so memory's vector search is targeted
            # at the sub-task's domain rather than the whole conversation.
            recent: List[str] = []
            if context:
                recent.append(context[:1000])
            recent.append(task_description)
            mem_data = await memory_adapter.assemble_prompt(
                agent_id=agent_id_int,
                context={
                    "task_type": required_capabilities or "general",
                    "domain": "",
                    "recent_messages": recent,
                    # Hints downstream consumers (the prompt assembler) can
                    # read to bias retrieval. Today they're best-effort —
                    # the assembler may ignore unknown keys.
                    "sub_agent_depth": new_depth,
                },
                trace_id=trace_id,
            )
            mem_prompt = mem_data.get("system_prompt", "")
            if mem_prompt:
                system_prompt += f"\nYOUR MEMORY CONTEXT:\n{mem_prompt[:1000]}\n"
        except Exception:
            pass

    # 5. Recursively call agent_execute
    sub_request = AgentExecuteRequest(
        messages=[
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=task_description),
        ],
        tools=sub_tools if sub_tools else parent_body.tools,
        tool_executor_url=parent_body.tool_executor_url,
        provider=selected_provider,
        model=selected_model,
        temperature=parent_body.temperature,
        max_tokens=parent_body.max_tokens,
        max_iterations=parent_body.max_iterations,
        max_continuations=parent_body.max_continuations,
        team_id=parent_body.team_id,
        graph_id=parent_body.graph_id,
        parent_node_id=sub_node_id,
        current_depth=new_depth,
        max_sub_agent_depth=parent_body.max_sub_agent_depth,
        conversation_id=parent_body.conversation_id,
    )

    sub_response = await agent_execute(sub_request, request)

    sub_elapsed = int((time.monotonic() - sub_start) * 1000)

    # 6. Update TaskNode status in Neo4j
    if neo4j:
        try:
            status = "SUCCESS" if sub_response.success else "FAILED"
            cypher = (
                "MATCH (n:TaskNode {node_id: $node_id}) "
                "SET n.status = $status, n.execution_time_ms = $ms, "
                "n.assigned_agent_id = $agent_id, n.assigned_agent_name = $agent_name, "
                "n.updated_at = datetime()"
            )
            await neo4j.run_query(cypher, {
                "node_id": sub_node_id, "status": status, "ms": sub_elapsed,
                "agent_id": selected_agent_id or "", "agent_name": selected_agent_name,
            }, trace_id=trace_id)
        except Exception:
            pass

    # 7. Log AgentInteraction
    if neo4j:
        try:
            interaction_cypher = """
            CREATE (i:AgentInteraction {
                interaction_id: $iid, task_id: $task_id, graph_id: $graph_id,
                agent_id: $agent_id, agent_name: $agent_name,
                interaction_type: 'SUB_AGENT_SPAWN',
                description: $desc, latency_ms: $latency,
                tools_used: $tools, trace_id: $trace_id,
                sub_agent_depth: $depth, parent_node_id: $parent_node_id,
                timestamp: datetime()
            })
            """
            await neo4j.run_query(interaction_cypher, {
                "iid": str(uuid.uuid4()), "task_id": sub_node_id,
                "graph_id": parent_body.graph_id or "",
                "agent_id": selected_agent_id or "", "agent_name": selected_agent_name,
                "desc": f"Sub-agent spawned: {task_description[:200]}",
                "latency": sub_elapsed,
                "tools": [t.name for t in (sub_tools or [])],
                "trace_id": trace_id, "depth": new_depth,
                "parent_node_id": parent_body.parent_node_id or "",
            }, trace_id=trace_id)
        except Exception:
            pass

    logger.info(
        "Sub-agent execution completed",
        layer="router",
        trace_id=trace_id,
        depth=new_depth,
        agent_name=selected_agent_name,
        success=sub_response.success,
        tool_calls=len(sub_response.tool_calls),
        sub_agent_calls=len(sub_response.sub_agent_calls),
        latency_ms=sub_elapsed,
    )

    return {
        "success": sub_response.success,
        "response": sub_response.response or "",
        "agent_name": selected_agent_name,
        "agent_id": selected_agent_id,
        "depth": new_depth,
        "node_id": sub_node_id,
        "tool_calls": len(sub_response.tool_calls),
        "latency_ms": sub_elapsed,
    }


def _build_openai_tools(tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
    """Convert our tool definitions to OpenAI function calling format."""
    openai_tools = []
    for t in tools:
        if t.tool_type == "DATABASE":
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": f"tool_{t.name.replace(' ', '_').lower()}",
                    "description": f"Execute a SQL query using the {t.name} database tool. {t.description}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The SQL query to execute",
                            }
                        },
                        "required": ["query"],
                    },
                },
            })
        elif t.tool_type == "API":
            # Build a rich description from the tool config so the LLM knows exact params
            api_desc = f"Make an HTTP API call using the {t.name} tool. {t.description}"
            base_url = t.config.get("base_url") or t.config.get("endpoint") or ""
            http_method = t.config.get("http_method", "GET")
            if base_url:
                api_desc += f"\nEndpoint: {http_method} {base_url}"
            # Include any default params from config so LLM knows the API structure
            default_params = t.config.get("default_params")
            if default_params and isinstance(default_params, dict):
                param_hints = ", ".join(f"{k} (e.g. {v})" for k, v in default_params.items())
                api_desc += f"\nKnown parameters: {param_hints}"

            openai_tools.append({
                "type": "function",
                "function": {
                    "name": f"tool_{t.name.replace(' ', '_').lower()}",
                    "description": api_desc,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query_params": {
                                "type": "object",
                                "description": f"Query parameters to append to the URL. The API base URL is: {base_url}",
                                "additionalProperties": {"type": "string"},
                            },
                            "body": {
                                "type": "object",
                                "description": "Request body for POST/PUT calls (ignored for GET)",
                            },
                        },
                        "required": ["query_params"] if http_method.upper() == "GET" else [],
                    },
                },
            })
        elif t.tool_type == "PYTHON":
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": f"tool_{t.name.replace(' ', '_').lower()}",
                    "description": f"Execute Python code using the {t.name} tool. {t.description}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {
                                "type": "string",
                                "description": "Python code with a def execute(inputs) function",
                            },
                            "inputs": {
                                "type": "object",
                                "description": "Input data for the execute function",
                            },
                        },
                        "required": ["code"],
                    },
                },
            })
        elif t.tool_type == "GITHUB":
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": f"tool_{t.name.replace(' ', '_').lower()}",
                    "description": f"Interact with GitHub using the {t.name} tool. {t.description}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "enum": ["read_file", "list_prs", "search_code"],
                                "description": "GitHub action to perform",
                            },
                            "query": {
                                "type": "string",
                                "description": "Search query or file path",
                            },
                        },
                    },
                },
            })
        elif t.tool_type == "GRAPH":
            graph_desc = f"Execute a Cypher query against the Neo4j graph database using the {t.name} tool. {t.description}"
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": f"tool_{t.name.replace(' ', '_').lower()}",
                    "description": graph_desc,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The Cypher query to execute against the Neo4j graph database",
                            },
                            "params": {
                                "type": "object",
                                "description": "Optional parameters for the Cypher query (e.g. {loan_id: 'LOAN001'})",
                            },
                        },
                        "required": ["query"],
                    },
                },
            })
        else:
            # Generic tool
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": f"tool_{t.name.replace(' ', '_').lower()}",
                    "description": f"Use the {t.name} tool. {t.description}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "input": {
                                "type": "string",
                                "description": "Input for the tool",
                            },
                        },
                    },
                },
            })
    return openai_tools


@router.post("/agent-execute", response_model=AgentExecuteResponse)
async def agent_execute(body: AgentExecuteRequest, request: Request) -> AgentExecuteResponse:
    """Execute an agent with tool-use loop and response continuation.

    Flow:
    1. Send messages + tool definitions to LLM (provider-aware)
    2. If LLM requests tool calls → execute them → feed results back → repeat
    3. If response is truncated (finish_reason=length) → auto-continue to get full response
    4. Aggregate all partial responses into one final response
    """
    trace_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    start = time.monotonic()
    all_tool_calls: List[ToolCallRecord] = []
    total_tokens = 0
    provider = body.provider

    logger.info(
        "Agent execute requested",
        layer="router",
        trace_id=trace_id,
        provider=provider,
        tool_count=len(body.tools),
        model=body.model,
    )

    all_sub_agent_calls: List[Dict[str, Any]] = []

    try:
        # Build tool name -> definition mapping
        tool_map: Dict[str, ToolDefinition] = {}
        openai_tools = _build_openai_tools(body.tools)
        for oai_tool, our_tool in zip(openai_tools, body.tools):
            func_name = oai_tool["function"]["name"]
            tool_map[func_name] = our_tool

        # Inject spawn_sub_agent tool if depth allows and team context is available
        can_spawn = (
            body.current_depth < body.max_sub_agent_depth
            and body.team_id is not None
        )
        if can_spawn:
            openai_tools.append(SPAWN_SUB_AGENT_TOOL)

        # Prepare messages (mutable copy)
        messages: List[Dict[str, Any]] = [{"role": m.role, "content": m.content} for m in body.messages]

        iterations = 0
        final_response = ""

        # ── Phase A: blackboard + memory refresh setup ─────────────────
        # Cursor "$" = only entries arriving from now on, so we don't replay
        # the entire stream. Each non-first iteration consumes from this cursor
        # and advances it. Only meaningful if conversation_id is present.
        redis_client = getattr(request.app.state, "redis", None)
        bb_cursor: str = "$"
        # Buffer the entities seen across this run so we don't repeatedly
        # query memory with the same string each iteration.
        seen_entities_global: set = set()
        # Track whether a memory refresh is pending — set when new entities
        # are discovered inside the tool-call loop, consumed before next LLM turn.
        pending_new_entities: List[str] = []

        while iterations < body.max_iterations:
            iterations += 1

            # ── Phase A.2/A.3: inject team context + memory refresh ────
            # Skip on iteration 1 — there's no prior tool result yet, and the
            # initial system+user messages already carry the assembled prompt.
            if iterations > 1 and body.conversation_id:
                try:
                    new_entries, bb_cursor = await blackboard.consume_new(
                        redis_client,
                        conversation_id=body.conversation_id,
                        last_id=bb_cursor,
                        exclude_agent_id=str(body.agent_id) if body.agent_id else "",
                    )
                    if new_entries:
                        ctx = blackboard.format_team_context(new_entries)
                        if ctx:
                            messages.append({"role": "user", "content": ctx})
                except Exception:
                    pass  # observability MUST NOT break the loop

                # Memory refresh — fire only when we actually discovered new
                # entities in the prior iteration's tool results.
                if pending_new_entities:
                    try:
                        refresh_text = await _memory_refresh(
                            agent_id=body.agent_id,
                            entities=pending_new_entities,
                            trace_id=trace_id,
                        )
                        if refresh_text:
                            messages.append({"role": "user", "content": refresh_text})
                            try:
                                await events.publish(
                                    conversation_id=body.conversation_id or "",
                                    kind="memory.refreshed",
                                    trace_id=trace_id,
                                    graph_id=body.graph_id,
                                    node_id=body.node_id,
                                    iteration=iterations,
                                    round_n=body.iteration_round,
                                    payload={
                                        "agent_id": body.agent_id,
                                        "agent_name": body.agent_name,
                                        "entities": pending_new_entities[:10],
                                        "preview": refresh_text[:280],
                                    },
                                )
                            except Exception:
                                pass
                    except Exception:
                        pass
                    pending_new_entities = []

            # Emit a per-iteration event so the timeline can render the
            # agent's reasoning steps.
            try:
                await events.publish(
                    conversation_id=body.conversation_id or "",
                    kind="agent.iteration",
                    trace_id=trace_id,
                    graph_id=body.graph_id,
                    node_id=body.node_id,
                    iteration=iterations,
                    round_n=body.iteration_round,
                    payload={
                        "agent_id": body.agent_id,
                        "agent_name": body.agent_name,
                        "depth": body.current_depth,
                        "msg_count": len(messages),
                    },
                )
            except Exception:
                pass

            # Call LLM with tools (provider-aware)
            result = await _llm_adapter.complete_with_tools(
                messages=messages,
                tools=openai_tools if openai_tools else None,
                model=body.model,
                temperature=body.temperature,
                max_tokens=body.max_tokens,
                trace_id=trace_id,
                provider=provider,
            )

            if result.get("usage"):
                total_tokens += result["usage"].get("total_tokens", 0)
                # Phase B.2: feed real-time token spend into the per-conv
                # budget so sub-agent spawn gates have current numbers.
                if body.conversation_id:
                    try:
                        u = result["usage"]
                        await budget.add_tokens(
                            redis_client,
                            conversation_id=body.conversation_id,
                            tokens_in=int(u.get("prompt_tokens", 0) or 0),
                            tokens_out=int(u.get("completion_tokens", 0) or 0),
                        )
                    except Exception:
                        pass

            # If no tool calls, we have a text response
            if not result.get("tool_calls"):
                partial = result.get("content", "")
                final_response += partial

                # --- Response continuation: if truncated, ask LLM to continue ---
                finish = result.get("finish_reason", "")
                if finish == "length" and body.max_continuations > 0:
                    continuations = 0
                    while finish == "length" and continuations < body.max_continuations:
                        continuations += 1
                        logger.info("Response truncated, continuing", layer="router",
                                    trace_id=trace_id, continuation=continuations)
                        messages.append({"role": "assistant", "content": partial})
                        messages.append({"role": "user", "content": "Please continue from where you left off."})

                        cont_result = await _llm_adapter.complete_with_tools(
                            messages=messages,
                            tools=None,  # no tools during continuation
                            model=body.model,
                            temperature=body.temperature,
                            max_tokens=body.max_tokens,
                            trace_id=trace_id,
                            provider=provider,
                        )
                        if cont_result.get("usage"):
                            total_tokens += cont_result["usage"].get("total_tokens", 0)

                        partial = cont_result.get("content", "")
                        final_response += partial
                        finish = cont_result.get("finish_reason", "")
                        iterations += 1
                break

            # Process tool calls
            messages.append(result["assistant_message"])

            for tc in result["tool_calls"]:
                func_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {"raw": tc["function"]["arguments"]}

                # --- Sub-agent spawn handling ---
                if func_name == "spawn_sub_agent":
                    if body.current_depth >= body.max_sub_agent_depth:
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": json.dumps({
                                "error": f"Max sub-agent depth ({body.max_sub_agent_depth}) reached. "
                                         "Handle this task directly with your own tools."
                            }),
                        })
                        continue

                    # Phase B.2: token + spawn-count budget gate. Hits before
                    # we burn an LLM call to negotiate the sub-agent.
                    if body.conversation_id:
                        gate = await budget.can_spawn_sub_agent(
                            redis_client,
                            conversation_id=body.conversation_id,
                        )
                        if not gate.get("allowed"):
                            try:
                                await events.publish(
                                    conversation_id=body.conversation_id or "",
                                    kind="subagent.refused",
                                    trace_id=trace_id,
                                    graph_id=body.graph_id,
                                    node_id=body.node_id,
                                    iteration=iterations,
                                    round_n=body.iteration_round,
                                    status="DEVIATED",
                                    payload={
                                        "agent_id": body.agent_id,
                                        "agent_name": body.agent_name,
                                        "reason": gate.get("reason", ""),
                                        "snapshot": gate.get("snapshot", {}),
                                        "task_description": (arguments.get("task_description") or "")[:240],
                                    },
                                )
                            except Exception:
                                pass
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "content": json.dumps({
                                    "error": (
                                        "Conversation budget exhausted: "
                                        f"{gate.get('reason','unknown')}. "
                                        "Handle this task directly with your own tools "
                                        "or summarize what you have."
                                    ),
                                }),
                            })
                            continue
                        # Increment the spawn counter eagerly so concurrent
                        # spawns don't all squeeze under the same cap.
                        try:
                            await budget.add_sub_agent_spawn(
                                redis_client,
                                conversation_id=body.conversation_id,
                            )
                        except Exception:
                            pass

                    # Phase B.3: emit subagent.spawned BEFORE the recursive
                    # call so the timeline can render the parent→child edge
                    # in real time.
                    if body.conversation_id:
                        try:
                            await events.publish(
                                conversation_id=body.conversation_id,
                                kind="subagent.spawned",
                                trace_id=trace_id,
                                graph_id=body.graph_id,
                                node_id=body.node_id,
                                iteration=iterations,
                                round_n=body.iteration_round,
                                payload={
                                    "parent_agent_id": body.agent_id,
                                    "parent_agent_name": body.agent_name,
                                    "depth": body.current_depth + 1,
                                    "task_description": (arguments.get("task_description") or "")[:240],
                                    "required_capabilities": (arguments.get("required_capabilities") or "")[:160],
                                    "context_preview": (arguments.get("context") or "")[:200],
                                },
                            )
                        except Exception:
                            pass

                    sub_result = await _execute_sub_agent(
                        parent_body=body,
                        task_description=arguments.get("task_description", ""),
                        required_capabilities=arguments.get("required_capabilities", ""),
                        context=arguments.get("context", ""),
                        trace_id=trace_id,
                        request=request,
                    )

                    all_sub_agent_calls.append(sub_result)

                    all_tool_calls.append(ToolCallRecord(
                        tool_name="spawn_sub_agent",
                        tool_type="SUB_AGENT",
                        tool_id=sub_result.get("node_id", ""),
                        arguments=arguments,
                        result=sub_result.get("response", "")[:2000],
                        success=sub_result.get("success", False),
                        latency_ms=sub_result.get("latency_ms", 0),
                        is_sub_agent=True,
                        sub_agent_id=sub_result.get("agent_id"),
                        sub_agent_name=sub_result.get("agent_name"),
                        sub_agent_depth=sub_result.get("depth", 0),
                    ))

                    content = json.dumps({
                        "sub_agent_result": sub_result.get("response", ""),
                        "sub_agent_name": sub_result.get("agent_name", ""),
                        "success": sub_result.get("success", False),
                    }, default=str)
                    if len(content) > 8000:
                        content = content[:8000] + "\n... (truncated)"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": content,
                    })
                    continue

                # --- Normal tool execution ---
                tool_def = tool_map.get(func_name)
                if not tool_def:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": json.dumps({"error": f"Unknown tool: {func_name}"}),
                    })
                    continue

                # Phase A: emit tool.call event before execution so the UI can
                # show "in flight" state while we wait for the tool.
                try:
                    await events.publish(
                        conversation_id=body.conversation_id or "",
                        kind="tool.call",
                        trace_id=trace_id,
                        graph_id=body.graph_id,
                        node_id=body.node_id,
                        iteration=iterations,
                        round_n=body.iteration_round,
                        payload={
                            "agent_id": body.agent_id,
                            "agent_name": body.agent_name,
                            "tool_id": tool_def.tool_id,
                            "tool_name": tool_def.name,
                            "tool_type": tool_def.tool_type,
                            "args_preview": json.dumps(arguments, default=str)[:400],
                        },
                    )
                except Exception:
                    pass

                tool_result = await _execute_tool(
                    tool_executor_url=body.tool_executor_url,
                    tool_def=tool_def,
                    arguments=arguments,
                    trace_id=trace_id,
                )

                all_tool_calls.append(ToolCallRecord(
                    tool_name=tool_def.name,
                    tool_type=tool_def.tool_type,
                    tool_id=tool_def.tool_id,
                    arguments=arguments,
                    result=tool_result.get("output") if tool_result.get("success") else tool_result.get("error"),
                    success=tool_result.get("success", False),
                    latency_ms=tool_result.get("latency_ms", 0),
                ))

                content = json.dumps(tool_result.get("output", tool_result.get("error", "No result")), default=str)
                if len(content) > 8000:
                    content = content[:8000] + "\n... (truncated)"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": content,
                })

                # ── Phase A: post-tool fan-out ─────────────────────────
                # 1) Extract entities for next iteration's memory refresh.
                # 2) Publish a tool.result event for the UI timeline.
                # 3) Publish a blackboard tool_result_summary so siblings see it.
                try:
                    new_entities = _extract_entities(content)
                    fresh = [e for e in new_entities if e.lower() not in seen_entities_global]
                    for e in fresh:
                        seen_entities_global.add(e.lower())
                    if fresh:
                        pending_new_entities.extend(fresh[:10])
                except Exception:
                    fresh = []

                try:
                    await events.publish(
                        conversation_id=body.conversation_id or "",
                        kind="tool.result",
                        trace_id=trace_id,
                        graph_id=body.graph_id,
                        node_id=body.node_id,
                        iteration=iterations,
                        round_n=body.iteration_round,
                        status="SUCCESS" if tool_result.get("success") else "ERROR",
                        payload={
                            "agent_id": body.agent_id,
                            "agent_name": body.agent_name,
                            "tool_id": tool_def.tool_id,
                            "tool_name": tool_def.name,
                            "tool_type": tool_def.tool_type,
                            "success": tool_result.get("success", False),
                            "latency_ms": tool_result.get("latency_ms", 0),
                            "preview": content[:400],
                            "discovered_entities": fresh[:10],
                        },
                    )
                except Exception:
                    pass

                if body.conversation_id:
                    try:
                        await blackboard.publish(
                            redis_client,
                            conversation_id=body.conversation_id,
                            kind="tool_result_summary",
                            agent_id=str(body.agent_id) if body.agent_id else "",
                            agent_name=body.agent_name or "",
                            node_id=body.node_id or "",
                            iteration=iterations,
                            payload={
                                "tool_name": tool_def.name,
                                "tool_type": tool_def.tool_type,
                                "success": bool(tool_result.get("success")),
                                "summary": (content[:240] + "…") if len(content) > 240 else content,
                                "discovered_entities": fresh[:10],
                            },
                            trace_id=trace_id,
                        )
                    except Exception:
                        pass

            logger.info(
                "Agent tool-use iteration",
                layer="router",
                trace_id=trace_id,
                iteration=iterations,
                tool_calls_count=len(result["tool_calls"]),
                depth=body.current_depth,
            )

        elapsed = int((time.monotonic() - start) * 1000)

        logger.info(
            "Agent execute completed",
            layer="router",
            trace_id=trace_id,
            provider=provider,
            iterations=iterations,
            total_tool_calls=len(all_tool_calls),
            sub_agent_count=len(all_sub_agent_calls),
            depth=body.current_depth,
            latency_ms=elapsed,
        )

        return AgentExecuteResponse(
            success=True,
            response=final_response,
            model=body.model or "default",
            latency_ms=elapsed,
            tokens_used=total_tokens or None,
            tool_calls=all_tool_calls,
            iterations=iterations,
            trace_id=trace_id,
            sub_agent_calls=all_sub_agent_calls,
        )

    except Exception as exc:
        elapsed = int((time.monotonic() - start) * 1000)
        logger.error(
            "Agent execute failed",
            layer="router",
            trace_id=trace_id,
            error=str(exc),
            latency_ms=elapsed,
        )
        return AgentExecuteResponse(
            success=False,
            error=str(exc),
            latency_ms=elapsed,
            tool_calls=all_tool_calls,
            trace_id=trace_id,
            sub_agent_calls=all_sub_agent_calls,
        )


async def _execute_tool(
    tool_executor_url: str,
    tool_def: ToolDefinition,
    arguments: Dict[str, Any],
    trace_id: str,
) -> Dict[str, Any]:
    """Execute a tool by calling the tool executor endpoint.

    Normalizes LLM arguments to the format expected by each tool executor:
    - API tools: wrap raw params into query_params if not already wrapped
    - DATABASE tools: pass as-is (expects {query: "..."})
    - PYTHON tools: pass as-is (expects {code: "...", inputs: {...}})
    """
    import httpx

    # Normalize arguments based on tool type
    inputs = dict(arguments)
    if tool_def.tool_type == "API":
        # If LLM sent raw params (no query_params/body key), wrap them
        if "query_params" not in inputs and "body" not in inputs:
            # All top-level keys are query params
            inputs = {"query_params": {k: str(v) for k, v in inputs.items()}}

    payload = {
        "tool_id": tool_def.tool_id,
        "tool_type": tool_def.tool_type,
        "config": tool_def.config,
        "inputs": inputs,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                tool_executor_url,
                json=payload,
                headers={"x-request-id": trace_id, "content-type": "application/json"},
            )
            data = resp.json()
            return data
    except Exception as exc:
        logger.error(
            "Tool execution failed",
            layer="router",
            trace_id=trace_id,
            tool_name=tool_def.name,
            error=str(exc),
        )
        return {"success": False, "error": str(exc), "latency_ms": 0}
