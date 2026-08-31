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

# Known AU court abbreviations (medium-neutral forms). Anything claiming to be
# a citation but using an unknown abbreviation is itself a fabrication signal.
_KNOWN_COURTS = (
    "HCA", "FCA", "FCAFC", "NSWSC", "NSWCA", "NSWDC", "NSWLEC", "NSWCCA",
    "VSC", "VSCA", "QSC", "QCA", "SASC", "SASCFC", "WASC", "WASCA",
    "TASSC", "TASCCA", "ACTSC", "ACTCA", "NTSC", "NTCA", "FedCFamC1", "FedCFamC2",
)
_COURT_ALT = "|".join(sorted(_KNOWN_COURTS, key=len, reverse=True))
_MEDIUM_NEUTRAL = re.compile(
    rf"\[\d{{4}}\]\s*(?:{_COURT_ALT})\s*\d+", re.ASCII
)  # e.g. [2023] NSWSC 1101
_TRUNCATED_MEDIUM = re.compile(
    rf"\[\d{{4}}\]\s*(?:{_COURT_ALT})\b(?!\s*\d)", re.ASCII
)  # e.g. "RPS v R [2019] NSWCA" — incomplete citation form; verify as FLAGGED
_UNKNOWN_COURT_CITE = re.compile(
    rf"\[\d{{4}}\]\s*(?!{_COURT_ALT}\b)[A-Z]{{2,10}}(?:\s+\d+)?", re.ASCII
)  # e.g. "[2014] NSW 687" or "[2014] NSW" — not a real court; verify as FLAGGED (fabrication signal)
_ACT_REF = re.compile(
    r"\b([A-Z][A-Za-z'’\-]+(?:\s+[A-Z][A-Za-z'’\-]+)*\s+Act\s+\d{4}\s*(?:\(Cth\)|\((?:NSW|VIC|QLD|SA|WA|TAS|ACT|NT)\))?)", re.ASCII
)  # e.g. "Civil Liability Act 2002 (NSW)" — at least one capitalised word + "Act YYYY"


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
    """Pull medium-neutral case citations and Act references from document text.

    G7: any candidate containing a deny-list token (e.g. "austlii") is dropped
    at extraction — deny words are not citations and must never reach a URL
    template. check_frl/check_nsw_caselaw also re-assert via _denylisted().
    """
    found: list[str] = []
    seen: set[str] = set()
    for m in _MEDIUM_NEUTRAL.finditer(text):
        c = re.sub(r"\s+", " ", m.group(0).strip())
        if c.lower() in seen or _denylisted(c):
            continue
        seen.add(c.lower())
        found.append(c)
    def _push(cand: str) -> None:
        c = re.sub(r"\s+", " ", cand.strip())
        if not c or c.lower() in seen or _denylisted(c):
            return
        seen.add(c.lower())
        found.append(c)

    for m in _UNKNOWN_COURT_CITE.finditer(text):
        _push(m.group(0))
    for m in _TRUNCATED_MEDIUM.finditer(text):
        _push(m.group(0))  # extraction includes truncated; verification marks FLAGGED
    for m in _ACT_REF.finditer(text):
        c = m.group(1).strip()
        if len(c) > 6:
            _push(c)
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
            elif _UNKNOWN_COURT_CITE.match(ref) and not _MEDIUM_NEUTRAL.match(ref):
                # unknown court abbreviation in a bracket cite — fabricated-citation signal
                findings.append(CitationFinding(ref, CitationStatus.FLAGGED, "parser"))
                continue
            elif _TRUNCATED_MEDIUM.match(ref):
                # incomplete citation form — can never verify; flagged for human review
                findings.append(CitationFinding(ref, CitationStatus.FLAGGED, "parser"))
                continue
            else:
                f = await check_frl(ref, c)
            findings.append(f or CitationFinding(ref, CitationStatus.UNVERIFIED, "parser"))
    finally:
        if own_client:
            await c.aclose()
    return findings