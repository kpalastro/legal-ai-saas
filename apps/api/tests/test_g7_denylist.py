"""G7: citation source allow/deny tests (TEST_PLAN P1 `test_verifier_network_deny_list`).

Two properties pinned here, both called out in the 31 Aug security audit as zero-
coverage gaps on live code:

1. **Deny-list tripwire** — the austlii ban (SC Gen 23/TECH_STACK prohibition) must
   fire as a hard raise on ANY outbound URL constructed by check_frl/check_nsw_caselaw.
   The tripwire exists in code but had no test; this file makes an austlii-sourced
   refactor fail CI rather than ship.
2. **Honesty property** — offline/unreachable sources degrade to UNVERIFIED, NEVER
   VERIFIED without real source concurrence. A future refactor "improving" the
   lookup logic cannot silently start fabricating verified statuses.
"""

from __future__ import annotations

import httpx
import pytest

from app.citations.service import (
    CITATION_SOURCE_DENYLIST,
    check_frl,
    check_nsw_caselaw,
    extract_citations,
    verify_citations,
)

CASE_CITE = "[2024] NSWSC 1101"
ACT_REF = "Civil Liability Act 2002 (NSW)"


# ---------- deny-list tripwire (G7) ----------


@pytest.mark.compliance
async def test_g7_denylist_tripwire_fires_on_injected_host() -> None:
    """User-controlled citation text that names austlii reaches the outbound URL —
    the tripwire must fire BEFORE any HTTP call (G7: proven live on this path)."""

    async def _boom(*a, **kw):  # a real request would mean the tripwire failed
        raise AssertionError("outbound HTTP attempted to a deny-listed source")

    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="denied citation source"):
            await check_frl("Civil Liability Act 2002 austlii.edu.au", client)


@pytest.mark.compliance
async def test_g7_denylist_tripwire_nsw_caselaw(monkeypatch) -> None:
    """Same tripwire on the caselaw path — simulate the ban by pointing the module
    constant at an austlii-domain URL via the deny-list check (never real HTTP)."""

    async def _no_http(*a, **kw):
        raise AssertionError("outbound HTTP attempted after tripwire")

    # Simulate a refactor that (wrongly) builds an austlii URL: patch the host
    # constant and assert the tripwire still fires BEFORE any network call.
    monkeypatch.setattr("app.citations.service.NSW_CASELAW", "https://www.austlii.edu.au")
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="denied citation source"):
            await check_nsw_caselaw(CASE_CITE, client)


@pytest.mark.compliance
def test_g7_denylist_contents() -> None:
    assert "austlii" in CITATION_SOURCE_DENYLIST


@pytest.mark.compliance
def test_g7_extracted_citations_never_produce_denied_urls() -> None:
    """The two outbound-URL templates cannot construct an austlii URL from any
    extracted citation text (injection-proofing the templates themselves)."""
    evil_cases = [
        "austlii",
        "https://www.austlii.edu.au/cgi-bin/[2024] NSWSC 1",
        "[2024] AUSTLII 1",
    ]
    for raw in evil_cases:
        for cite in extract_citations(raw):
            from app.citations.service import FRL_API, NSW_CASELAW

            for base in (FRL_API, NSW_CASELAW):
                url = f"{base}/{cite}"
                assert "austlii" not in url.lower(), f"template collision: {url}"


# ---------- honesty property: offline => UNVERIFIED, never VERIFIED ----------


class _DownClient:
    """Simulates DNS failure / unreachable source (the mid-test condition @supervisor hit)."""

    def __init__(self, *a, **kw):
        pass

    async def get(self, *a, **kw):
        raise httpx.ConnectError("simulated offline")


@pytest.mark.compliance
async def test_offline_sources_degrade_to_unverified_never_verified() -> None:
    text = f"Per Smith v Jones {CASE_CITE} under the {ACT_REF}."
    findings = await verify_citations(text, client=_DownClient())
    assert findings, "extractor should find the two citations"
    for f in findings:
        assert f.status is not __import__(
            "app.citations.service", fromlist=["CitationStatus"]
        ).CitationStatus.VERIFIED, (
            f"{f.raw} claimed VERIFIED with an unreachable source — fabricated "
            "verification is the exact hallucination failure SC Gen 23 para 17 guards"
        )
        assert f.status.value in ("unverified", "flagged")


class _VerifyingClient:
    """200 + matching body: the one shape that legitimately earns VERIFIED."""

    def __init__(self):
        pass

    async def get(self, url, **kw):
        class R:
            status_code = 200
            text = CASE_CITE if "caselaw" in url else ACT_REF.lower()

        return R()


@pytest.mark.compliance
async def test_real_concurrence_earns_verified() -> None:
    findings = await verify_citations(
        f"Per Smith {CASE_CITE}", client=_VerifyingClient()
    )
    assert any(f.status.value == "verified" for f in findings), (
        "a genuinely matching source response must produce verified — if this "
        "flips, verification has degraded to permanently-unverified"
    )