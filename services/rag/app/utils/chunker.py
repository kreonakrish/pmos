import re
from typing import List

from app.utils.logger import get_logger

logger = get_logger(layer="chunker")


class DocumentChunker:
    """
    Splits raw text into overlapping chunks using one of three strategies:
    - fixed:     Split by character count with configurable overlap.
    - sentence:  Split on sentence boundaries (period + space/newline).
    - paragraph: Split on double newlines.
    """

    def chunk(
        self,
        text: str,
        strategy: str = "fixed",
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> List[str]:
        if not text or not text.strip():
            return []

        strategy = strategy.lower()
        if strategy == "fixed":
            return self._fixed_chunks(text, chunk_size, overlap)
        elif strategy == "sentence":
            return self._sentence_chunks(text, chunk_size, overlap)
        elif strategy == "paragraph":
            return self._paragraph_chunks(text, chunk_size, overlap)
        else:
            logger.warning(f"Unknown chunking strategy '{strategy}', falling back to 'fixed'")
            return self._fixed_chunks(text, chunk_size, overlap)

    # ------------------------------------------------------------------
    # Private strategies
    # ------------------------------------------------------------------

    def _fixed_chunks(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        if len(text) <= chunk_size:
            return [text]

        chunks: List[str] = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunks.append(text[start:end])
            start += chunk_size - overlap
            if start >= len(text):
                break
        return chunks

    def _sentence_chunks(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        # Split on sentence-ending punctuation followed by whitespace or end of string
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        sentences = [s.strip() for s in sentences if s.strip()]

        if not sentences:
            return []

        chunks: List[str] = []
        current = ""
        overlap_buf: List[str] = []

        for sentence in sentences:
            candidate = (current + " " + sentence).strip() if current else sentence
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                    # build overlap buffer from tail of current chunk
                    overlap_buf = self._tail_sentences(current, overlap)
                current = (" ".join(overlap_buf) + " " + sentence).strip()

        if current:
            chunks.append(current)

        return chunks

    def _paragraph_chunks(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        paragraphs = re.split(r"\n\n+", text.strip())
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        if not paragraphs:
            return []

        chunks: List[str] = []
        current = ""

        for para in paragraphs:
            candidate = (current + "\n\n" + para).strip() if current else para
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                # Trim overlap from end of current chunk
                overlap_text = current[-overlap:] if overlap and current else ""
                current = (overlap_text + "\n\n" + para).strip()

        if current:
            chunks.append(current)

        return chunks

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tail_sentences(text: str, max_len: int) -> List[str]:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        buf: List[str] = []
        total = 0
        for s in reversed(sentences):
            if total + len(s) + 1 <= max_len:
                buf.insert(0, s)
                total += len(s) + 1
            else:
                break
        return buf
