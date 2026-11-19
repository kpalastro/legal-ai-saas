"""Persist citation verification evidence as immutable case snapshots."""

from __future__ import annotations

import hashlib
from datetime import datetime

from sqlalchemy import text

from app.citations.service import CitationFinding


def _hash(finding: CitationFinding) -> str:
    material = "|".join(
        [
            finding.raw,
            finding.status.value,
            finding.source,
            finding.url or "",
            finding.evidence or "",
            finding.checked_at or "",
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()


async def store_snapshots(db, case_id: str, findings: list[CitationFinding]) -> int:
    stored = 0
    for finding in findings:
        result = await db.execute(
            text(
                "INSERT INTO public.authority_snapshots"
                " (case_id, raw, status, source, url, evidence, checked_at, content_sha256)"
                " VALUES (:c, :r, :s, :src, :u, :e, :at, :h)"
                " ON CONFLICT (case_id, raw, content_sha256) DO NOTHING"
                " RETURNING id"
            ),
            {
                "c": case_id,
                "r": finding.raw,
                "s": finding.status.value,
                "src": finding.source,
                "u": finding.url,
                "e": finding.evidence,
                "at": datetime.fromisoformat(finding.checked_at)
                if finding.checked_at
                else None,
                "h": _hash(finding),
            },
        )
        if result.scalar_one_or_none() is not None:
            stored += 1
    return stored
