"""LLM-driven capability spec generator."""
from __future__ import annotations

import json
import uuid
from typing import Any

from app.adapters.llm_adapter import LLMAdapter, get_llm_adapter
from app.config import settings
from app.utils.logger import get_logger
from app.utils.metrics import SPECS_GENERATED_TOTAL

logger = get_logger(layer="service")


class SpecGeneratorService:
    """Generates validated capability specs from gap descriptions via LLM."""

    def __init__(self, llm: LLMAdapter | None = None) -> None:
        self._llm = llm or get_llm_adapter()

    # ── Prompt builders (dynamic, never static strings) ───────────────────────

    def _build_tool_prompt(self, gap_description: str) -> str:
        allowed = settings.meta_allowed_imports
        return f"""You are an AI system architect generating a Python TOOL capability.

Capability gap:
{gap_description}

Generate a self-contained Python function that addresses this gap.

Requirements:
- Only use imports from this whitelist: {allowed}
- The main function MUST be named "run" and accept keyword arguments
- Include comprehensive docstring
- Include 3 test cases that validate the function behaviour

Respond with a JSON object:
{{
  "capability_type": "TOOL",
  "name": "<short snake_case name>",
  "description": "<one-sentence description>",
  "spec_json": {{
    "code": "<complete Python source as a string — no triple backticks inside>",
    "config_schema": {{
      "<param_name>": {{"type": "<str|int|float|list|dict>", "description": "<desc>"}}
    }},
    "test_cases": [
      {{"input": {{}}, "expected_output": null, "description": "<what this tests>"}}
    ],
    "dependencies": ["<module1>", "<module2>"]
  }}
}}
"""

    def _build_skill_prompt(self, gap_description: str) -> str:
        return f"""You are an AI system architect generating a SKILL capability (reasoning pattern).

Capability gap:
{gap_description}

Generate a skill definition that addresses this reasoning gap.

Respond with a JSON object:
{{
  "capability_type": "SKILL",
  "name": "<short snake_case name>",
  "description": "<one-sentence description>",
  "spec_json": {{
    "prompt_template": "<system prompt template with {{{{placeholders}}}}>>",
    "reasoning_pattern": "<chain-of-thought outline>",
    "few_shot_examples": [
      {{"input": "<example input>", "output": "<expected reasoning + answer>"}}
    ],
    "domains": ["<domain1>"],
    "test_cases": [],
    "dependencies": [],
    "code": ""
  }}
}}
"""

    def _build_agent_prompt(self, gap_description: str) -> str:
        return f"""You are an AI system architect generating an AGENT capability definition.

Capability gap:
{gap_description}

Generate a full agent configuration to fill this gap.

Respond with a JSON object:
{{
  "capability_type": "AGENT",
  "name": "<short snake_case name>",
  "description": "<one-sentence description>",
  "spec_json": {{
    "role": "<agent role title>",
    "system_prompt_seed": "<initial system prompt seed>",
    "required_tools": ["<tool1>"],
    "domains": ["<domain1>"],
    "initial_score_band": {{"low": 0.3, "high": 0.7}},
    "memory_seeds": [
      {{"tier": "long_term", "content": "<relevant background knowledge>"}}
    ],
    "test_cases": [],
    "dependencies": [],
    "code": ""
  }}
}}
"""

    def _build_spec_prompt(self, gap_description: str, capability_type: str) -> str:
        """Select the correct prompt template based on capability type."""
        cap_type = capability_type.upper()
        if cap_type == "TOOL":
            return self._build_tool_prompt(gap_description)
        if cap_type == "SKILL":
            return self._build_skill_prompt(gap_description)
        if cap_type == "AGENT":
            return self._build_agent_prompt(gap_description)
        # Default to TOOL
        return self._build_tool_prompt(gap_description)

    def _parse_spec(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Normalise and validate the raw LLM JSON into a canonical spec shape."""
        spec_json = raw.get("spec_json", {})

        # Ensure mandatory top-level keys exist
        spec: dict[str, Any] = {
            "capability_type": str(raw.get("capability_type", "TOOL")).upper(),
            "name": str(raw.get("name", "unnamed_capability")),
            "description": str(raw.get("description", "")),
            "spec_json": {
                "code": str(spec_json.get("code", "")),
                "config_schema": spec_json.get("config_schema", {}),
                "test_cases": spec_json.get("test_cases", []),
                "dependencies": spec_json.get("dependencies", []),
                **{
                    k: v
                    for k, v in spec_json.items()
                    if k not in ("code", "config_schema", "test_cases", "dependencies")
                },
            },
        }
        return spec

    # ── Public API ────────────────────────────────────────────────────────────

    async def generate_spec(
        self,
        gap_description: str,
        capability_type: str,
        trace_id: str = "",
    ) -> dict[str, Any]:
        """Generate a capability spec via LLM; always audit-logs full content."""
        trace_id = trace_id or str(uuid.uuid4())
        logger.info(
            "spec_generation_started",
            trace_id=trace_id,
            capability_type=capability_type,
            gap_description=gap_description,
            layer="service",
        )

        prompt = self._build_spec_prompt(gap_description, capability_type)

        try:
            raw = await self._llm.complete_json(prompt)
        except Exception as exc:
            SPECS_GENERATED_TOTAL.labels(outcome="failed").inc()
            logger.error(
                "spec_generation_llm_error",
                trace_id=trace_id,
                error=str(exc),
                layer="service",
            )
            raise

        spec = self._parse_spec(raw)

        # CRITICAL: Audit log — always emit full spec content at INFO level
        logger.info(
            "spec_generated",
            trace_id=trace_id,
            capability_type=spec["capability_type"],
            spec_name=spec["name"],
            gap_description=gap_description,
            spec_content=spec,  # full content for audit trail
            layer="service",
        )

        return spec
