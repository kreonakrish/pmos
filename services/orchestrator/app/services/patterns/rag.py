"""RAGPattern — questions explicitly anchored to a document.

Triggers when the user mentions a filename / extension or phrasings
like "according to <document>", "in this report.pdf", "as per the
attached deck". Today the agent loop ALWAYS retrieves RAG context as
augmentation; this pattern carves out the case where the right answer
is RAG-only (no agent loop, no DB tools)."""

from __future__ import annotations

import re

from app.services.patterns.types import (
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
    Subtask,
)


# Same set the translator's _detect_explicit_routing_hints uses.
_DOC_EXTENSIONS = (
    "docx", "doc", "pdf", "xlsx", "xls", "csv", "txt", "md",
    "pptx", "ppt", "html", "htm", "rtf",
)
_DOC_EXT_RE = re.compile(
    r"\b[\w.\-]+\.(?:" + "|".join(_DOC_EXTENSIONS) + r")\b",
    re.IGNORECASE,
)
_DOC_PHRASE_RE = re.compile(
    r"\b(?:according\s+to|as\s+per|in\s+(?:the\s+)?(?:document|report|"
    r"deck|attachment|file|pdf|memo|presentation|paper|article)|"
    r"based\s+on\s+(?:the\s+)?(?:document|report|deck|attachment|"
    r"file|pdf|memo|presentation|paper|article))\b",
    re.IGNORECASE,
)


class RAGPattern:
    name = "rag"
    priority = 80

    async def detect(self, ctx: DispatchContext) -> PatternMatch:
        q = ctx.question or ""
        if not q.strip():
            return PatternMatch(score=0.0, threshold=0.55, explanation="empty question")

        evidence = []
        score = 0.0

        m = _DOC_EXT_RE.search(q)
        if m:
            evidence.append(f"document filename mentioned: {m.group(0)!r}")
            score = max(score, 0.85)

        if _DOC_PHRASE_RE.search(q):
            evidence.append("phrase 'according to <doc>' / 'as per <doc>' matched")
            score = max(score, 0.7)

        if score == 0.0:
            return PatternMatch(
                score=0.0,
                threshold=0.55,
                explanation="no document reference",
            )

        return PatternMatch(
            score=score,
            threshold=0.55,
            evidence=evidence,
            explanation="explicit document reference — answer from RAG, not agents",
            payload={"document_hit": m.group(0) if m else None},
        )

    async def plan(self, ctx: DispatchContext, match: PatternMatch) -> ExecutionPlan:
        # RAG-only synthesis: a single subtask that retrieves + answers.
        # Phase 4 wires this to the orchestrator's RAG adapter and a
        # dedicated synthesis prompt that bypasses the agent loop.
        return ExecutionPlan(
            subtasks=[
                Subtask(
                    description=f"[rag-only] {ctx.question}",
                    metadata={"kind": "rag_only"},
                )
            ],
            aggregation="rag_synthesis",
            metadata={
                "kind": "rag_only",
                "document_hit": match.payload.get("document_hit"),
            },
        )

    async def execute(self, ctx: DispatchContext, plan: ExecutionPlan) -> ExecutionResult:
        return ExecutionResult(response="", extras={"pattern": self.name})
