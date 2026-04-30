"""Shared mixins / helpers for pattern implementations.

Patterns import the agent-loop runner from the host pipeline via
constructor injection — this file only carries cross-pattern utilities
(e.g. "extract column name from question") so we don't duplicate
them across every detect()."""

from __future__ import annotations

import re
from typing import Optional, Tuple


# Same identifier shapes the translator uses for column extraction.
_QUOTED_RE = re.compile(r"['\"`]([a-zA-Z][a-zA-Z0-9_]*)['\"`]")
_FIELD_NAMED_RE = re.compile(
    r"\b(?:column|columns|field|fields|attribute|attributes)\s+"
    r"(?:named\s+|called\s+)?([a-zA-Z][a-zA-Z0-9_]*)\b",
    re.IGNORECASE,
)
_SNAKE_THEN_FIELD_RE = re.compile(
    r"\b([a-zA-Z][a-zA-Z0-9_]*?_[a-zA-Z][a-zA-Z0-9_]*)\s+"
    r"(?:columns?|fields?|attributes?)\b",
    re.IGNORECASE,
)
_BARE_THEN_FIELD_RE = re.compile(
    r"\b([a-zA-Z][a-zA-Z0-9_]*)\s+(?:columns?|fields?|attributes?)\b",
    re.IGNORECASE,
)
_VALUE_OF_SNAKE_RE = re.compile(
    r"\b(?:value|values|sample|samples|sampling|rows?|records?|data|"
    r"examples?)\s+(?:of|for|from|in)\s+(?:the\s+|each\s+|every\s+)?"
    r"([a-zA-Z][a-zA-Z0-9_]*?_[a-zA-Z][a-zA-Z0-9_]*)\b",
    re.IGNORECASE,
)
_SNAKE_THEN_VALUE_RE = re.compile(
    r"\b([a-zA-Z][a-zA-Z0-9_]*?_[a-zA-Z][a-zA-Z0-9_]*)\s+"
    r"(?:value|values|sample|samples|rows?|records?|data)\b",
    re.IGNORECASE,
)

_STOP = frozenset({
    "the", "a", "an", "any", "every", "all", "some", "many", "more",
    "this", "that", "these", "those", "your", "their", "such", "same",
    "primary", "foreign", "unique", "common", "shared", "related",
    "named", "called", "specific", "particular", "given",
})
_SKIP_EXTRA = frozenset({
    "table", "tables", "database", "databases", "schema", "schemas",
    "dataset", "datasets", "system", "systems",
    "catalog", "catalogs", "store", "stores",
    "column", "columns", "field", "fields",
    "attribute", "attributes", "property", "properties",
    "value", "values", "sample", "samples", "row", "rows",
    "record", "records", "data", "name", "id",
})


def extract_column_name(question: str) -> Optional[str]:
    """Best-effort column-name extraction. Tries patterns in priority
    order — quoted > "column named X" > "<snake>_id column" > bare
    "<word> column". Skips obvious non-columns ("the", "tables", ...).
    Returns ``None`` when nothing usable is found."""
    if not question:
        return None
    for pat in (_QUOTED_RE, _FIELD_NAMED_RE, _VALUE_OF_SNAKE_RE,
                _SNAKE_THEN_VALUE_RE, _SNAKE_THEN_FIELD_RE,
                _BARE_THEN_FIELD_RE):
        for m in pat.finditer(question):
            cand = (m.group(1) or "").strip()
            cl = cand.lower()
            if not cand or cl in _STOP or cl in _SKIP_EXTRA or len(cl) < 2:
                continue
            return cand
    return None


def parse_sample_count(question: str, default: int = 5) -> int:
    """Pull "<N> rows / sample of <N> / first <N> / top <N> / limit <N>"
    out of the user's wording. Clamped to [1, 1000]."""
    if not question:
        return default
    m = re.search(
        r"\b(?:sample(?:\s+of)?|of|first|top|limit)\s*(\d{1,4})\b",
        question, re.IGNORECASE,
    )
    if not m:
        m = re.search(
            r"\b(\d{1,4})\s*(?:samples?|rows?|values?|records?)\b",
            question, re.IGNORECASE,
        )
    if not m:
        return default
    try:
        n = int(m.group(1))
    except (TypeError, ValueError):
        return default
    return max(1, min(n, 1000))
