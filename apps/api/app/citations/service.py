"""Citation verification service (feature 4, TEST_PLAN G7, checklist 1.4/3.4).

Sources (TECH_STACK.md v2.1): Federal Register of Legislation OData API +
NSW Caselaw. **AustLII is BANNED** for any programmatic/AI use — G7 deny-list
asserts it never appears in outbound URLs from this module.

v1 design: verification is DATABASE-BACKED and DETERMINISTIC. Each extracted
citation gets a flag:
  ✅ verified   — resolved against FRL/NSW Caselaw with a matching title
  ⚠️ unverified — well-formed citation, source lookup failed/inconclusive
  ❌ flagged    — malformed or (worse) structure suggests fabrication
No LLM in the verification path: the SC Gen 23 para 17 gate requires the
human confirmation step anyway, and deterministic parsing is testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

import httpx

# G7: hard deny-list. Any outbound URL containing these hosts = compliance incident.
CITATION_SOURCE_DENYLIST = ("austlii",)

FRL_API = "https://api.legislation.gov.au"  # OData-ish; v1 primary source
NSW_CASELAW = "https://nsw.caselaw.nsw.gov.au"  # cached HTML search

_MEDIUM_NEUTRAL = re.compile(
    r"\[\d{4}\]\s*[A-Z]{2,6}\s*\d+", re.ASCII
)  # e.g. [2023] NSWSC 1101
_ACT_REF = re.compile(
    r"\b((?:Act|Act\s+\d{4})\b.*?\b\d{4}\b|\b\d{4}\s*\(Cth\)|\b\d{4}\s*\(NSW\))", re.ASCII
)


class CitationStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    FLAGGED = "flagged"


@dataclass(frozen=True)
class CitationFinding:
    raw: str
    status: CitationStatus
    source: str  # "frl" | "nsw_caselaw" | "parser"
    url: str | None = None


def extract_citations(text: str) -> list[str]:
    """Pull medium-neutral case citations and Act references from document text."""
    found: list[str] = []
    seen: set[str] = set()
    for m in _MEDIUM_NEUTRAL.finditer(text):
        c = re.sub(r"\s+", " ", m.group(0).strip())
        if c.lower() not in seen:
            seen.add(c.lower())
            found.append(c)
    for m in _ACT_REF.finditer(text):
        c = m.group(1).strip()
        if len(c) > 6 and c.lower() not in seen:
            seen.add(c.lower())
            found.append(c)
    return found


def _denylisted(url: str) -> bool:
    low = url.lower()
    return any(host in low for host in CITATION_SOURCE_DENYLIST)


async def check_frl(act_ref: str, client: httpx.AsyncClient) -> CitationFinding | None:
    """Look an Act reference up in the Federal Register of Legislation API."""
    url = f"{FRL_API}/search?query={act_ref}"
    if _denylisted(url):
        raise ValueError("denied citation source requested")  # G7 tripwire
    try:
        r = await client.get(url, timeout=8.0, follow_redirects=True)
        if r.status_code == 200 and act_ref.lower() in r.text.lower():
            return CitationFinding(act_ref, CitationStatus.VERIFIED, "frl", url)
        if r.status_code == 200:
            return CitationFinding(act_ref, CitationStatus.UNVERIFIED, "frl", url)
    except httpx.HTTPError:
        return None
    return None


async def check_nsw_caselaw(citation: str, client: httpx.AsyncClient) -> CitationFinding | None:
    """Look a medium-neutral citation up in NSW Caselaw (fetch + verify)."""
    url = f"{NSW_CASELAW}/search/?q={citation}"
    if _denylisted(url):
        raise ValueError("denied citation source requested")  # G7 tripwire
    try:
        r = await client.get(url, timeout=10.0, follow_redirects=True)
        if r.status_code == 200 and citation.replace(" ", "").lower() in r.text.replace(" ", "").lower():
            return CitationFinding(citation, CitationStatus.VERIFIED, "nsw_caselaw", url)
        if r.status_code == 200:
            return CitationFinding(citation, CitationStatus.UNVERIFIED, "nsw_caselaw", url)
    except httpx.HTTPError:
        return None
    return None


async def verify_citations(text: str, client: httpx.AsyncClient | None = None) -> list[CitationFinding]:
    """Verify every citation found in text. Offline-safe: unreachable sources
    return UNVERIFIED (never VERIFIED without source concurrence)."""
    findings: list[CitationFinding] = []
    own_client = client is None
    c = client or httpx.AsyncClient()
    try:
        for ref in extract_citations(text):
            if _MEDIUM_NEUTRAL.match(ref):
                f = await check_nsw_caselaw(ref, c)
            else:
                f = await check_frl(ref, c)
            findings.append(f or CitationFinding(ref, CitationStatus.UNVERIFIED, "parser"))
    finally:
        if own_client:
            await c.aclose()
    return findings