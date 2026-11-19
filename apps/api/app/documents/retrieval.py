"""Postgres full-text retrieval over case document chunks.

Deterministic and local: no embeddings, no external service, no data egress.
The query is the case's own issues/cause/title; ranking is ts_rank over the
English tsvector generated on document_chunks.
"""

from __future__ import annotations

import re

from sqlalchemy import text


def _tsquery(query: str) -> str:
    """OR the meaningful terms.

    `plainto_tsquery` ANDs every term, so a query built from several issues
    (plus `contract_breach` punctuation) matches nothing and silently falls back
    to the first chunks. OR-ing the terms lets a chunk that covers one issue
    rank above irrelevant background material.
    """
    words = re.findall(r"[A-Za-z0-9]{2,}", query)[:12]
    return " | ".join(words)


async def retrieve_chunks(
    db, *, case_id: str, query: str, limit: int = 6
) -> list[dict]:
    """Return relevant chunks (fallback: earliest chunks) with source filename."""
    rows = []
    tsq = _tsquery(query)
    if tsq:
        rows = (
            await db.execute(
                text(
                    """
                    WITH q AS (SELECT to_tsquery('english', :q) AS tsq)
                    SELECT c.content, c.chunk_index, d.original_filename,
                           ts_rank(c.search, q.tsq) AS rank
                    FROM public.document_chunks c
                    JOIN public.documents d ON d.id = c.document_id
                    CROSS JOIN q
                    WHERE c.case_id = :case AND c.search @@ q.tsq
                    ORDER BY rank DESC, c.chunk_index
                    LIMIT :limit
                    """
                ),
                {"case": case_id, "q": tsq, "limit": limit},
            )
        ).mappings().all()

    if not rows:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT c.content, c.chunk_index, d.original_filename
                    FROM public.document_chunks c
                    JOIN public.documents d ON d.id = c.document_id
                    WHERE c.case_id = :case
                    ORDER BY c.chunk_index
                    LIMIT :limit
                    """
                ),
                {"case": case_id, "limit": limit},
            )
        ).mappings().all()

    return [dict(row) for row in rows]
