"""Split extracted document text into retrievable chunks.

Chunks are ~1,200 characters with 150-character overlap, split preferentially on
paragraph/sentence boundaries. Retrieval (app/documents/retrieval.py) uses
Postgres full-text search over these chunks, so a long exhibit does not have to
fit in the prompt in full.
"""

from __future__ import annotations

MAX_CHUNKS = 200


def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length and len(chunks) < MAX_CHUNKS:
        end = min(start + size, length)
        if end < length:
            window = text[start:end]
            cut = max(
                window.rfind("\n\n"),
                window.rfind("\n"),
                window.rfind(". "),
                window.rfind("; "),
            )
            if cut > size // 2:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks
