"""Text cleaning and chunking utilities."""

from html import unescape
import re

try:
    from src.config import CHUNK_OVERLAP_WORDS, CHUNK_SIZE_WORDS
except ModuleNotFoundError:  # Allows: python src/ingest.py
    from config import CHUNK_OVERLAP_WORDS, CHUNK_SIZE_WORDS  # type: ignore


def clean_text(text: object) -> str:
    """Clean raw text while preserving medical terms and punctuation."""

    if text is None:
        return ""

    text = str(text)
    text = unescape(text)
    text = text.replace("\x00", " ")

    # Replace any run of spaces, tabs, or newlines with one space.
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def split_text_into_chunks(
    text: str,
    chunk_size_words: int = CHUNK_SIZE_WORDS,
    chunk_overlap_words: int = CHUNK_OVERLAP_WORDS,
) -> list[str]:
    """Split text into overlapping word chunks.

    Example:
    - chunk_size_words=180 means each chunk has up to 180 words.
    - chunk_overlap_words=40 means neighboring chunks share 40 words.
    """

    cleaned = clean_text(text)
    if not cleaned:
        return []

    if chunk_size_words <= 0:
        raise ValueError("chunk_size_words must be greater than 0.")

    if chunk_overlap_words < 0:
        raise ValueError("chunk_overlap_words cannot be negative.")

    if chunk_overlap_words >= chunk_size_words:
        raise ValueError("chunk_overlap_words must be smaller than chunk_size_words.")

    words = cleaned.split()

    if len(words) <= chunk_size_words:
        return [" ".join(words)]

    chunks = []
    start = 0

    while start < len(words):
        end = start + chunk_size_words
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))

        if end >= len(words):
            break

        start = end - chunk_overlap_words

    return chunks
