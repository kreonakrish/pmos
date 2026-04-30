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

    Phase 1: empty — the dispatcher will run, find no candidates, and
    record a no-winner trace alongside the legacy routing. Each later
    phase adds a pattern here.
    """
    return PatternRegistry()
