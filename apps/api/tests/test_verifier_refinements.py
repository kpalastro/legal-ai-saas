"""Verifier refinement tests (31 Aug late addendum): truncated + unknown-court citations."""

from __future__ import annotations

import pytest

from app.citations.service import (
    CitationStatus,
    extract_citations,
)


@pytest.mark.compliance
def test_truncated_medium_neutral_extracted_and_flagged() -> None:
    """RPS v R [2019] NSWCA — incomplete form must be surfaced as flagged, not invisible."""
    finds = extract_citations("In RPS v R [2019] NSWCA the court...")
    assert "[2019] NSWCA" in finds

    import asyncio
    from app.citations.service import verify_citations

    async def go():
        return await verify_citations("In RPS v R [2019] NSWCA the court held X.")

    findings = asyncio.run(go())
    statuses = {f.raw: f.status for f in findings}
    assert statuses["[2019] NSWCA"] == CitationStatus.FLAGGED


@pytest.mark.compliance
def test_unknown_court_cite_is_flagged_not_verifiable() -> None:
    """[2014] NSW 687 — 'NSW' isn't a court; a fabricated-citation signal lands FLAGGED."""
    import asyncio
    from app.citations.service import verify_citations

    findings = asyncio.run(verify_citations("Per Adeels Palace v Moubarak [2014] NSW 687."))
    statuses = {f.raw: f.status for f in findings}
    assert statuses.get("[2014] NSW 687") == CitationStatus.FLAGGED


@pytest.mark.compliance
def test_known_court_abbreviations_only():
    """[2023] NSWSC 1101 still extracts fine (no allowlist over-reach)."""
    assert "[2023] NSWSC 1101" in extract_citations("Per [2023] NSWSC 1101.")


@pytest.mark.compliance
def test_bare_act_fragment_noise_suppressed() -> None:
    """Tightened act regex kills standalone 'Act 2002' rows; full names still caught."""
    finds = extract_citations("The Act 2002 says nothing; but the Civil Liability Act 2002 (NSW) does.")
    assert "Act 2002" not in finds
    assert any("Civil Liability Act 2002" in f for f in finds)


@pytest.mark.compliance
def test_denylisted_token_never_extracted() -> None:
    """G7: deny words can't pass through extraction into a URL template."""
    assert extract_citations("[2024] AUSTLII 1") == []
    assert extract_citations("austlii") == []
    assert extract_citations("https://www.austlii.edu.au/cgi-bin/[2024] NSWSC 1") == ["[2024] NSWSC 1"]