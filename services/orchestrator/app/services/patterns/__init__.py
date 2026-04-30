"""Question-pattern dispatcher for the orchestrator.

The orchestrator routes each user question to exactly one ``QuestionPattern``
(Report, Metadata, ColumnValue, Business, RAG, …). Each pattern owns its
own detect → plan → execute lifecycle so adding a new pattern is one
class, not a new branch in a 250-line ``if/elif`` chain.

The dispatcher records a ``DecisionTrace`` for every request — every
candidate pattern's score and reasoning — so the Pipeline-Jobs UI can
show *why* a question was routed where it was.

See ``ARCHITECTURE.md`` and the patterns sketch in the conversation log
for the design rationale.
"""

from app.services.patterns.dispatcher import PatternDispatcher
from app.services.patterns.registry import PatternRegistry, build_default_registry
from app.services.patterns.types import (
    CandidateScore,
    DecisionTrace,
    DispatchContext,
    ExecutionPlan,
    ExecutionResult,
    PatternMatch,
    QuestionPattern,
    Subtask,
    TeamContext,
)

__all__ = [
    "CandidateScore",
    "DecisionTrace",
    "DispatchContext",
    "ExecutionPlan",
    "ExecutionResult",
    "PatternDispatcher",
    "PatternMatch",
    "PatternRegistry",
    "QuestionPattern",
    "Subtask",
    "TeamContext",
    "build_default_registry",
]
