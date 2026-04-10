"""Unit tests for DocumentChunker — no external dependencies."""
import pytest

from app.utils.chunker import DocumentChunker


@pytest.fixture
def chunker():
    return DocumentChunker()


# ---------------------------------------------------------------------------
# Fixed strategy
# ---------------------------------------------------------------------------


def test_fixed_correct_chunk_size(chunker):
    text = "a" * 1000
    chunks = chunker.chunk(text, strategy="fixed", chunk_size=200, overlap=0)
    assert all(len(c) <= 200 for c in chunks)
    assert len(chunks) == 5


def test_fixed_overlap_applied(chunker):
    text = "a" * 100
    chunks = chunker.chunk(text, strategy="fixed", chunk_size=40, overlap=10)
    # With overlap, successive chunks share characters
    assert len(chunks) >= 3
    # Check overlap: end of chunk[0] should equal start of chunk[1]
    assert chunks[0][-10:] == chunks[1][:10]


def test_fixed_text_shorter_than_chunk_size(chunker):
    text = "short text"
    chunks = chunker.chunk(text, strategy="fixed", chunk_size=500, overlap=50)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_fixed_exact_chunk_size(chunker):
    text = "a" * 500
    chunks = chunker.chunk(text, strategy="fixed", chunk_size=500, overlap=0)
    assert len(chunks) == 1
    assert len(chunks[0]) == 500


def test_fixed_empty_string(chunker):
    assert chunker.chunk("", strategy="fixed") == []


def test_fixed_whitespace_only(chunker):
    assert chunker.chunk("   \n\t  ", strategy="fixed") == []


# ---------------------------------------------------------------------------
# Sentence strategy
# ---------------------------------------------------------------------------


def test_sentence_splits_on_periods(chunker):
    text = "First sentence. Second sentence. Third sentence."
    chunks = chunker.chunk(text, strategy="sentence", chunk_size=30, overlap=0)
    assert len(chunks) >= 2
    # Each chunk should not be absurdly long
    assert all(len(c) <= 60 for c in chunks)


def test_sentence_empty_string(chunker):
    assert chunker.chunk("", strategy="sentence") == []


def test_sentence_single_short(chunker):
    text = "Hello world."
    chunks = chunker.chunk(text, strategy="sentence", chunk_size=500, overlap=0)
    assert len(chunks) == 1
    assert "Hello" in chunks[0]


# ---------------------------------------------------------------------------
# Paragraph strategy
# ---------------------------------------------------------------------------


def test_paragraph_splits_on_double_newline(chunker):
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    chunks = chunker.chunk(text, strategy="paragraph", chunk_size=30, overlap=0)
    assert len(chunks) >= 2


def test_paragraph_empty_string(chunker):
    assert chunker.chunk("", strategy="paragraph") == []


def test_paragraph_no_double_newline(chunker):
    text = "Only one paragraph here without breaks."
    chunks = chunker.chunk(text, strategy="paragraph", chunk_size=500, overlap=0)
    assert len(chunks) == 1


# ---------------------------------------------------------------------------
# Unknown strategy fallback
# ---------------------------------------------------------------------------


def test_unknown_strategy_falls_back_to_fixed(chunker):
    text = "a" * 200
    chunks = chunker.chunk(text, strategy="unknown", chunk_size=100, overlap=0)
    assert len(chunks) == 2
