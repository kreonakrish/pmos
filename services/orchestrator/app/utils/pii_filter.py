"""Config-driven PII filter for redacting sensitive content from responses.

The filter is applied at the response boundary — just before an assistant
message is persisted to MySQL and returned to the caller — so any PII that
slips through the LLM never escapes the orchestrator.

Patterns are loaded from (in priority order):
  1. The YAML file at services/orchestrator/config/pii_patterns.yaml
     (path overridable by the PII_PATTERNS_FILE env var).
  2. A built-in default list covering SSN, US phone, email, credit-card
     shaped numbers, IBAN, and DOB-shaped strings.

The filter compiles every regex once at construction time so the per-call
cost is just the scan itself.

Allowlist:
  - Specific values (e.g. ``support@pmos.example``) can be allowlisted in
    the config so they are never redacted. Matching is case-insensitive
    exact-string against the matched span.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Pattern, Set, Tuple

from pydantic import BaseModel

try:  # pragma: no cover - YAML is optional; we fall back to defaults.
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None  # type: ignore


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_PATTERNS: List[Dict[str, str]] = [
    {"kind": "SSN", "regex": r"\b\d{3}-\d{2}-\d{4}\b"},
    {"kind": "EMAIL", "regex": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"},
    {"kind": "PHONE_US", "regex": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"},
    {"kind": "CREDIT_CARD", "regex": r"\b(?:\d[ -]*?){13,19}\b"},
    {"kind": "IBAN", "regex": r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b"},
    {"kind": "DOB", "regex": r"\b(?:19|20)\d{2}[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])\b"},
]


def _default_config_path() -> str:
    """Resolve the bundled default YAML path relative to the repo layout."""
    here = os.path.dirname(os.path.abspath(__file__))
    # services/orchestrator/app/utils/pii_filter.py -> services/orchestrator/config/pii_patterns.yaml
    return os.path.normpath(os.path.join(here, "..", "..", "config", "pii_patterns.yaml"))


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------


class Redaction(BaseModel):
    """A single redaction applied to the input text."""

    kind: str
    span: Tuple[int, int]
    replacement: str


class RedactionResult(BaseModel):
    """Output of :meth:`PIIFilter.redact`."""

    redacted_text: str
    redactions: List[Redaction]


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------


class PIIFilter:
    """Redacts sensitive content using a configurable pattern list.

    Construction is the only expensive step — every regex is compiled once
    and reused for the lifetime of the instance.

    Parameters
    ----------
    config_path:
        Optional path to the YAML config file. If ``None`` we use
        ``$PII_PATTERNS_FILE`` if set, otherwise the bundled default path.
        If the resolved path does not exist or YAML is unavailable, we fall
        back to :data:`DEFAULT_PATTERNS` and an empty allowlist.
    extra_patterns:
        Optional list of ``{"kind": str, "regex": str}`` dicts merged on
        top of the loaded patterns (mostly useful in tests).
    """

    _REPLACEMENT_FMT = "[REDACTED:{kind}]"

    def __init__(
        self,
        config_path: Optional[str] = None,
        extra_patterns: Optional[Iterable[Dict[str, str]]] = None,
    ) -> None:
        self._config_path = (
            config_path
            or os.environ.get("PII_PATTERNS_FILE")
            or _default_config_path()
        )
        raw_patterns, allowlist = self._load_config(self._config_path)
        if extra_patterns:
            raw_patterns = list(raw_patterns) + list(extra_patterns)

        self._compiled: List[Tuple[str, Pattern[str]]] = []
        for entry in raw_patterns:
            kind = entry.get("kind")
            regex = entry.get("regex")
            if not kind or not regex:
                continue
            try:
                self._compiled.append((str(kind), re.compile(regex)))
            except re.error:
                # Skip a single bad pattern rather than break the whole filter.
                continue

        # Allowlist — case-insensitive exact-match against each matched span.
        self._allowlist: Set[str] = {v.lower() for v in allowlist}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def redact(self, text: str) -> RedactionResult:
        """Redact sensitive content from ``text``.

        Returns a :class:`RedactionResult`. If no patterns match, the
        ``redacted_text`` field is the *exact same string object* (no
        allocation) and ``redactions`` is empty.
        """
        if not text or not self._compiled:
            return RedactionResult(redacted_text=text or "", redactions=[])

        # First pass: collect all matches across all patterns.
        matches: List[Tuple[int, int, str]] = []  # (start, end, kind)
        for kind, pattern in self._compiled:
            for m in pattern.finditer(text):
                start, end = m.span()
                if start == end:
                    continue
                matched_value = text[start:end]
                if matched_value.lower() in self._allowlist:
                    continue
                matches.append((start, end, kind))

        if not matches:
            # No allocation — return the original string instance.
            return RedactionResult(redacted_text=text, redactions=[])

        # Resolve overlaps: prefer the earliest start; on tie prefer the
        # longer match (more specific). Sort then sweep.
        matches.sort(key=lambda t: (t[0], -(t[1] - t[0])))
        non_overlapping: List[Tuple[int, int, str]] = []
        cursor = -1
        for start, end, kind in matches:
            if start < cursor:
                continue  # overlaps a previously kept match
            non_overlapping.append((start, end, kind))
            cursor = end

        # Second pass: build the redacted string in a single allocation.
        out_parts: List[str] = []
        redactions: List[Redaction] = []
        last = 0
        for start, end, kind in non_overlapping:
            if start > last:
                out_parts.append(text[last:start])
            replacement = self._REPLACEMENT_FMT.format(kind=kind)
            out_parts.append(replacement)
            redactions.append(
                Redaction(kind=kind, span=(start, end), replacement=replacement)
            )
            last = end
        if last < len(text):
            out_parts.append(text[last:])

        return RedactionResult(redacted_text="".join(out_parts), redactions=redactions)

    # ------------------------------------------------------------------
    # Config loading
    # ------------------------------------------------------------------

    @staticmethod
    def _load_config(path: str) -> Tuple[List[Dict[str, str]], List[str]]:
        """Load patterns + allowlist from YAML, falling back to defaults.

        Returns ``(patterns, allowlist_values)``. Any failure to read or
        parse the file falls back to :data:`DEFAULT_PATTERNS` with an
        empty allowlist.
        """
        if yaml is None or not path or not os.path.isfile(path):
            return list(DEFAULT_PATTERNS), []

        try:
            with open(path, "r", encoding="utf-8") as f:
                data: Any = yaml.safe_load(f)
        except Exception:
            return list(DEFAULT_PATTERNS), []

        if not isinstance(data, dict):
            return list(DEFAULT_PATTERNS), []

        patterns_raw = data.get("patterns")
        if not isinstance(patterns_raw, list) or not patterns_raw:
            patterns: List[Dict[str, str]] = list(DEFAULT_PATTERNS)
        else:
            patterns = [p for p in patterns_raw if isinstance(p, dict)]

        allowlist_values: List[str] = []
        allowlist = data.get("allowlist")
        if isinstance(allowlist, dict):
            for bucket in allowlist.values():
                if isinstance(bucket, list):
                    allowlist_values.extend(str(v) for v in bucket if v is not None)
        elif isinstance(allowlist, list):
            allowlist_values = [str(v) for v in allowlist if v is not None]

        return patterns, allowlist_values


# Module-level convenience singleton — orchestrator hot-path uses this so
# we don't recompile regexes on every request. Tests should construct
# their own instance to control config path / extra patterns.
_default_filter: Optional[PIIFilter] = None


def get_default_filter() -> PIIFilter:
    """Lazily build and cache a process-wide default :class:`PIIFilter`."""
    global _default_filter
    if _default_filter is None:
        _default_filter = PIIFilter()
    return _default_filter


def reset_default_filter() -> None:
    """Drop the cached default filter (useful for tests / hot-reload)."""
    global _default_filter
    _default_filter = None
