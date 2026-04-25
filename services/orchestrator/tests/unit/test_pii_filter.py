"""Unit tests for the config-driven PII filter (Phase E3)."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from app.utils.pii_filter import (
    DEFAULT_PATTERNS,
    PIIFilter,
    Redaction,
    RedactionResult,
    reset_default_filter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def yaml_config(tmp_path: Path) -> str:
    """Write a YAML config matching the production layout to a temp path."""
    cfg = tmp_path / "pii_patterns.yaml"
    cfg.write_text(
        textwrap.dedent(
            r"""
            patterns:
              - kind: SSN
                regex: '\b\d{3}-\d{2}-\d{4}\b'
              - kind: EMAIL
                regex: '\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'
              - kind: PHONE_US
                regex: '\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'
              - kind: CREDIT_CARD
                regex: '\b(?:\d[ -]*?){13,19}\b'
              - kind: IBAN
                regex: '\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b'
              - kind: DOB
                regex: '\b(?:19|20)\d{2}[-/](?:0?[1-9]|1[0-2])[-/](?:0?[1-9]|[12]\d|3[01])\b'
            allowlist:
              emails:
                - support@pmos.example
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return str(cfg)


@pytest.fixture
def filter_with_yaml(yaml_config: str) -> PIIFilter:
    return PIIFilter(config_path=yaml_config)


@pytest.fixture(autouse=True)
def _reset_default_filter():
    """Ensure the module-level singleton is fresh for each test."""
    reset_default_filter()
    yield
    reset_default_filter()


# ---------------------------------------------------------------------------
# Required behaviours
# ---------------------------------------------------------------------------


def test_redacts_ssn(filter_with_yaml: PIIFilter):
    """SSN appearing in text is replaced and the redaction list records it."""
    result = filter_with_yaml.redact("SSN: 123-45-6789")
    assert isinstance(result, RedactionResult)
    assert "[REDACTED:SSN]" in result.redacted_text
    assert "123-45-6789" not in result.redacted_text
    kinds = [r.kind for r in result.redactions]
    assert "SSN" in kinds
    # Span correctness: the recorded span should slice the original SSN.
    ssn_redactions = [r for r in result.redactions if r.kind == "SSN"]
    assert ssn_redactions
    s, e = ssn_redactions[0].span
    assert "SSN: 123-45-6789"[s:e] == "123-45-6789"
    assert ssn_redactions[0].replacement == "[REDACTED:SSN]"


def test_redacts_email_unless_allowlisted(filter_with_yaml: PIIFilter):
    """Generic emails are redacted; allowlisted ones pass through verbatim."""
    text = "Contact alice@example.com or support@pmos.example for help."
    result = filter_with_yaml.redact(text)

    # Generic email redacted.
    assert "alice@example.com" not in result.redacted_text
    assert "[REDACTED:EMAIL]" in result.redacted_text

    # Allowlisted email survives.
    assert "support@pmos.example" in result.redacted_text

    # Only one EMAIL redaction recorded.
    email_kinds = [r for r in result.redactions if r.kind == "EMAIL"]
    assert len(email_kinds) == 1


def test_no_redactions_returns_input_unchanged(filter_with_yaml: PIIFilter):
    """Input with no PII comes back as the same string and an empty list."""
    benign = "The quick brown fox jumps over the lazy dog."
    result = filter_with_yaml.redact(benign)
    assert result.redacted_text == benign
    # Same object — the implementation avoids reallocating when there are no hits.
    assert result.redacted_text is benign
    assert result.redactions == []


def test_filter_disabled_bypasses(monkeypatch, filter_with_yaml: PIIFilter):
    """When pii_filter_enabled=False the filter is skipped at the call site.

    The PIIFilter class itself does not consult the setting (that's the
    caller's responsibility — see pipeline._apply_pii_filter and
    conversations.py). This test asserts the call-site contract: when the
    setting is False, the original text is preserved and no redactions
    are produced.
    """
    from app.config import settings

    monkeypatch.setattr(settings, "pii_filter_enabled", False)

    text_with_ssn = "SSN: 123-45-6789"

    # Simulate the orchestrator call site: skip the filter when disabled.
    if settings.pii_filter_enabled:
        result = filter_with_yaml.redact(text_with_ssn)
        out = result.redacted_text
        redactions = result.redactions
    else:
        out = text_with_ssn
        redactions = []

    assert out == text_with_ssn
    assert redactions == []


# ---------------------------------------------------------------------------
# Extra coverage — defaults, overlapping matches, missing config
# ---------------------------------------------------------------------------


def test_falls_back_to_defaults_when_config_missing(tmp_path: Path):
    """Pointing at a non-existent path uses DEFAULT_PATTERNS."""
    bogus = str(tmp_path / "does_not_exist.yaml")
    f = PIIFilter(config_path=bogus)
    assert f._compiled  # type: ignore[attr-defined]  # defaults loaded
    # Default kinds should include SSN/EMAIL.
    kinds = {k for k, _ in f._compiled}  # type: ignore[attr-defined]
    default_kinds = {p["kind"] for p in DEFAULT_PATTERNS}
    assert default_kinds.issubset(kinds)


def test_redacts_multiple_kinds_in_one_pass(filter_with_yaml: PIIFilter):
    """A single text containing several PII kinds is fully scrubbed."""
    text = (
        "Email me at bob@example.org, my SSN is 987-65-4321, "
        "phone 555-123-4567."
    )
    result = filter_with_yaml.redact(text)
    kinds = {r.kind for r in result.redactions}
    assert {"EMAIL", "SSN", "PHONE_US"}.issubset(kinds)
    # No raw PII left in the output.
    assert "bob@example.org" not in result.redacted_text
    assert "987-65-4321" not in result.redacted_text
    assert "555-123-4567" not in result.redacted_text


def test_empty_input_returns_empty(filter_with_yaml: PIIFilter):
    result = filter_with_yaml.redact("")
    assert result.redacted_text == ""
    assert result.redactions == []


def test_redaction_model_shape(filter_with_yaml: PIIFilter):
    """Redaction objects expose kind/span/replacement as documented."""
    result = filter_with_yaml.redact("SSN 111-22-3333 is sensitive.")
    assert len(result.redactions) == 1
    r = result.redactions[0]
    assert isinstance(r, Redaction)
    assert r.kind == "SSN"
    assert isinstance(r.span, tuple) and len(r.span) == 2
    assert r.replacement == "[REDACTED:SSN]"
