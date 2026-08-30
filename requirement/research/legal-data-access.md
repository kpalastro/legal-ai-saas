# Research: Legal Data Access Track
*Recovered from child agent transcript, 26 August 2026*

## AustLII Usage Policy — AI Use Explicitly Prohibited

**Source:** https://www.austlii.edu.au/austlii/copyright.html (via Wayback: web.archive.org/web/20260419153648/https://www8.austlii.edu.au/austlii/copyright.html)

Key prohibitions:
- (c): "AustLII is not a data repository and does not provide a service for other publishers or systems to obtain documents from AustLII for republication or for uses related to artificial intelligence (AI-related use) or other automated systems."
- (e): "AustLII specifically restricts, via the Robots Exclusion Protocol (REP), all spiders and other automated agents from accessing and copying its case-law. Additionally, AustLII blocks automated access to all materials for AI-related uses across its entire collection."
- 5(a): "AustLII's legal materials may not be used, directly or indirectly, to train, fine-tune, evaluate, develop, operate, or provide inputs to artificial intelligence systems"
- 5(b)(ii): Prohibits "creating embeddings, vector representations, semantic indexes, knowledge graphs, or other computational derivatives"
- 5(b)(v): Prohibits "integration of AustLII materials into AI-enabled legal reasoning, research, advice, prediction, classification, triage, or decision-support systems"

**Technical evidence:** AustLII is behind Cloudflare bot challenge (cf-mitigated: challenge). robots.txt disallows /au/cases/, /cases/, /*? (all search). Explicit blocks for Google-Extended and Apple-Extended AI crawlers.

## Federal Register of Legislation API (FRL)

**URL:** https://api.prod.legislation.gov.au/swagger/index.html
**Swagger spec:** v1/swagger.json (Legislation Public API v1)
**Status:** Live, no auth required, OData endpoints
**Coverage:** Commonwealth legislation only (not case law)
**Endpoints:** /v1/content, /v1/documents, /v1/departments, /v1/search, etc.
**Terms:** https://www.legislation.gov.au/Content/Disclaimer
**Contact:** feedback@legislation.gov.au

## NSW Caselaw

**URL:** https://www.caselaw.nsw.gov.au
**Status:** Fetchable HTML (no Cloudflare block detected)
**Coverage:** NSW courts/tribunals 1999-present (Court of Appeal, Court of Criminal Appeal, Supreme Court, District Court, Local Court, NCAT, etc.)
**API:** None found (/api, /feed return 404)
**Terms:** /terms returns 404 (no explicit AI ban found, but verify before automated use)

## JADE / BarNet

**URL:** https://jade.io
**Status:** JS-heavy, some endpoints accessible
**API:** Limited API exists (3 endpoints per parse.bot marketplace listing)
**Pricing:** JADE Professional $95/month or $995/year
**Terms:** Commercial terms at jade.io/terms (BarNetwork Pty Limited)
**Coverage:** Australian case law + legislation; editorial enhancements, citations (LawCite)

## Federal Court

**URL:** https://www.fedcourt.gov.au/digital-law-library
**Status:** Cloudflare-blocked (403) — same issue as AustLII

## High Court of Australia

**URL:** https://www.hcourt.gov.au/cases/recent-judgments
**Status:** Fetchable (200), but /cases/recent-judgments returned 404

## Australian AI Citation Hallucination Incidents

### 1. Valu v Minister for Immigration and Multicultural Affairs (No 2) [2025] FedCFamC2G 94
- NSW practitioner filed submissions with 17 non-existent cases and fabricated AAT quotes (ChatGPT-generated)
- Federal Circuit and Family Court of Australia (Division 2)
- Judge Skaros referred to OLSC
- Hearing vacated, significant court time wasted
- Sources: qlsproctor.com.au/2025/02/fake-cases-derail-lawyers-submissions; en.wikisource.org/wiki/Valu_v_Minister

### 2. Mr Dayal (Victorian lawyer, September 2025)
- First Australian lawyer formally sanctioned for AI-hallucinated citations
- Stripped of ability to practise as a principal lawyer
- Federal Circuit and Family Court
- Source: theguardian.com/law/2025/sep/03/lawyer-caught-using-ai-generated-false-citations
