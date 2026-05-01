"""Unit tests for TranslatorPipeline._detect_entity_count_question
(Phase 9B).

Mirrors the orchestrator-side disqualifier in entity_count.py: when a
question piles on attribute requests beyond the leading 'how many X',
the translator must NOT stamp intent='entity_count_question'. Otherwise
EntityCountPattern (priority 86) wins on the translator hint and the
new bid contract / set cover machinery never runs because BusinessPattern
(priority 50) doesn't get a chance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # services/translator/
_REPO_ROOT = _SERVICE_ROOT.parents[1]
for p in (_REPO_ROOT, _SERVICE_ROOT):
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

from app.services.pipeline import TranslatorPipeline  # noqa: E402


# ---------------------------------------------------------------------------
# Pre-Phase-9B baseline cases (must keep passing)
# ---------------------------------------------------------------------------

def test_detects_simple_count():
    is_q, entity = TranslatorPipeline._detect_entity_count_question(
        "how many total loans are there in the system"
    )
    assert is_q is True
    assert entity == "loans"


def test_detects_count_of_borrowers():
    is_q, entity = TranslatorPipeline._detect_entity_count_question(
        "count of borrowers"
    )
    assert is_q is True
    assert entity == "borrowers"


def test_rejects_table_question():
    is_q, entity = TranslatorPipeline._detect_entity_count_question(
        "how many tables have loan_id columns"
    )
    assert is_q is False


def test_rejects_predicate_question():
    is_q, entity = TranslatorPipeline._detect_entity_count_question(
        "how many loans have term_months > 300"
    )
    assert is_q is False


def test_rejects_aggregator_question():
    is_q, entity = TranslatorPipeline._detect_entity_count_question(
        "average loan amount across servicing"
    )
    assert is_q is False


def test_rejects_missing_count_verb():
    is_q, entity = TranslatorPipeline._detect_entity_count_question(
        "show me loans"
    )
    assert is_q is False


# ---------------------------------------------------------------------------
# Phase 9B — multi-attribute disqualifier
# ---------------------------------------------------------------------------

def test_rejects_marketing_campaign_compound_question():
    """The headline scenario. Pre-Phase-9 this returned (True, 'loans')
    and the dispatcher pinned to entity_count, never letting BusinessPattern
    bid."""
    q = (
        "How many loans were originated from the C0005 marketing "
        "campaign? When did they originate, how long have we serviced "
        "them, and what is their current status?"
    )
    is_q, entity = TranslatorPipeline._detect_entity_count_question(q)
    assert is_q is False, (
        "multi-attribute compound questions must NOT be stamped as "
        "entity_count_question — they belong to BusinessPattern"
    )


def test_rejects_compound_status_question():
    q = "How many active loans? What is their current status?"
    is_q, _ = TranslatorPipeline._detect_entity_count_question(q)
    assert is_q is False


def test_rejects_count_with_when_and_how_long():
    q = "How many loans? When did they originate, how long have we serviced them?"
    is_q, _ = TranslatorPipeline._detect_entity_count_question(q)
    assert is_q is False


def test_rejects_count_with_filter_code_and_when():
    q = "How many loans from CAMP-42, and when did they originate?"
    is_q, _ = TranslatorPipeline._detect_entity_count_question(q)
    assert is_q is False


def test_tolerates_one_signal():
    """A single 'from <CODE>' filter is one signal — not enough to
    demote. The agent figures out the filter at execution."""
    q = "how many loans from C0005"
    is_q, entity = TranslatorPipeline._detect_entity_count_question(q)
    assert is_q is True
    assert entity == "loans"


def test_tolerates_lowercase_geographic_filter():
    """'from california' is lowercase — the from-CODE regex requires an
    initial uppercase letter, so this does NOT count as a signal."""
    q = "how many loans from california"
    is_q, _ = TranslatorPipeline._detect_entity_count_question(q)
    assert is_q is True
