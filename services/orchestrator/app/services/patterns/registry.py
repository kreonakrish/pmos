"""Pattern registry.

Phase-1 build: an empty registry. Phase 3 fills it with the migrated
pattern classes one at a time. The default registry is what the
shadow-mode dispatcher walks; tests build their own with mocks.
"""

from __future__ import annotations

from typing import Iterable, List

from app.services.patterns.types import QuestionPattern


class PatternRegistry:
    """Thin ordered container — preserves insertion order so the
    dispatcher can fall back to it as the final tie-break."""

    def __init__(self, patterns: Iterable[QuestionPattern] = ()):
        self._patterns: List[QuestionPattern] = list(patterns)

    def __iter__(self):
        return iter(self._patterns)

    def __len__(self) -> int:
        return len(self._patterns)

    def all(self) -> List[QuestionPattern]:
        return list(self._patterns)

    def add(self, pattern: QuestionPattern) -> "PatternRegistry":
        self._patterns.append(pattern)
        return self


def build_default_registry() -> PatternRegistry:
    """Return the production pattern set.

    Phase 3: every pattern is registered. Order is the final tie-break
    when two patterns have the same priority — list the most specific
    detectors first.

    The dispatcher is still in shadow mode (Phase 1's flag) — these
    patterns score every request but routing is driven by the legacy
    if/elif gates until Phase 4.
    """
    # Local imports keep registry.py importable without pulling in
    # every pattern's deps when only the type is needed.
    from app.services.patterns.business import BusinessPattern
    from app.services.patterns.clarify import ClarifyPattern
    from app.services.patterns.column_value import ColumnValuePattern
    from app.services.patterns.entity_count import EntityCountPattern
    from app.services.patterns.freeform import FreeFormPattern
    from app.services.patterns.metadata import MetadataPattern
    from app.services.patterns.rag import RAGPattern
    from app.services.patterns.report import ReportPattern
    from app.services.patterns.team_self import TeamSelfPattern

    return PatternRegistry([
        TeamSelfPattern(),     # priority 95
        ReportPattern(),       # priority 90
        EntityCountPattern(),  # priority 86  — beats Clarify on count Qs
        ClarifyPattern(),      # priority 85
        RAGPattern(),          # priority 80
        MetadataPattern(),     # priority 70
        ColumnValuePattern(),  # priority 65
        BusinessPattern(),     # priority 50
        FreeFormPattern(),     # priority 0 (catch-all)
    ])
