# LexSim AI — Critical Review & Improvement Recommendations

**Reviewer:** Prime Agent autonomous review  
**Date:** 26 August 2026  
**Documents reviewed:** `REQUIREMENTS.md`, `ARCHITECTURE.md`, `REALTIME_COURTROOM.md`  
**Research method:** DuckDuckGo/Mojeek web search + primary-source verification (court practice notes, vendor pricing pages, HuggingFace model cards, Wayback Machine for Cloudflare-blocked pages)

---

## Executive Summary

LexSim AI has an ambitious and genuinely interesting product concept — a multi-agent courtroom debate simulation that predicts case outcomes and generates court-ready documents for Australian self-represented litigants (SRLs) and solo lawyers. The design documents are thorough in breadth.

However, **four foundational assumptions in the current design are wrong or unlawful**, and several more have significant gaps. The product cannot be built as specified. This review identifies the critical issues, provides evidence from primary sources, and proposes a revised architecture, cost model, and roadmap that would make the product viable.

### Critical Findings (ranked by severity)

| # | Finding | Severity | Status in current docs |
|---|---------|----------|----------------------|
| 1 | **AustLII prohibits all AI-related use** — no API, scraping banned, embeddings/RAG explicitly forbidden | **Blocker** | Docs assume "AustLII API" exists and is free |
| 2 | **DeepSeek-V3 cannot run on a single A100** — needs ~8×H200; cost is ~A$36k/mo, not $715/mo | **Blocker** | Docs specify 1×A100 at $1.43/hr |
| 3 | **NSW SC Gen 23 prohibits Gen AI in affidavits/witness statements** — directly conflicts with planned "affidavit generation" feature | **Blocker** | Docs list affidavit as a supported document type |
| 4 | **Outcome prediction marketed to vulnerable SRLs = misleading conduct risk** under ACL + UPL risk under Legal Profession Uniform Law | **High** | Docs set "70% accuracy" target with no methodology |
| 5 | **Self-hosting is economically irrational** — API inference costs A$0.14–1.71/case vs $49–149 price | **High** | Docs plan self-host SGLang/vLLM |
| 6 | **Two Australian lawyers already sanctioned for AI-hallucinated citations** (2024–2025) — citation verification is not optional | **High** | Docs have verification but via unlawful AustLII access |
| 7 | **No corporate legal-team readiness** — missing SSO/SAML, DMS integration, SOC 2, audit, DLP | **Medium** | Docs target only SRLs + small firms |
| 8 | **Architecture over-engineered for MVP** — Celery+Redis+WS+Kong+multi-cloud vs simple monolith | **Medium** | Docs plan 6-week MVP with full microservices |
| 9 | **Doc-internal inconsistencies** — 7-turn vs 9-turn, broken SQL, auth mismatch, voice quota math | **Low** | Throughout all three docs |

---

## 1. AustLII: The Citation Pipeline Is Unlawful As Designed

### The Problem

The entire citation-verification and RAG architecture depends on querying AustLII programmatically. **This is explicitly prohibited by AustLII's own usage policy.**

### Evidence

AustLII's Usage Policy (current, captured via Wayback Machine, April 2026 snapshot) states:

> **(c)** AustLII is not a data repository and does not provide a service for other publishers or systems to obtain documents from AustLII for republication or for uses related to artificial intelligence (AI-related use) or other automated systems.

> **(e)** AustLII specifically restricts, via the Robots Exclusion Protocol (REP), all spiders and other automated agents from accessing and copying its case-law. Additionally, AustLII blocks automated access to all materials for AI-related uses across its entire collection.

> **5(a)** AustLII's legal materials [...] may not be used, directly or indirectly, to train, fine-tune, evaluate, develop, operate, or provide inputs to artificial intelligence systems [...] This prohibition applies regardless of [the technical architecture or methodology used].

> **5(b)(ii)** Prohibited uses include: creating embeddings, vector representations, semantic indexes, knowledge graphs, or other computational derivatives of AustLII materials for use in automated or AI-enabled systems

> **5(b)(v)** Prohibited uses include: integration of AustLII materials into AI-enabled legal reasoning, research, advice, **prediction**, classification, triage, or decision-support systems

Source: `https://www.austlii.edu.au/austlii/copyright.html` (via Wayback: `web.archive.org/web/20260419153648/https://www8.austlii.edu.au/austlii/copyright.html`)

AustLII's `robots.txt` (captured Feb 2026) confirms: `Disallow: /au/cases/`, `Disallow: /cases/`, `Disallow: /*?` (all search results), plus explicit blocks for `Google-Extended` and `Apple-Extended` AI crawlers. The site is also behind Cloudflare's bot challenge (`cf-mitigated: challenge`), actively blocking automated access.

### What This Means

- **There is no AustLII API.** The `verify_citation()` function that "queries AustLII advanced search API" cannot be implemented.
- **Scraping is prohibited and technically blocked.** Cloudflare + robots.txt + explicit policy.
- **BGE-M3 embeddings of AustLII content for RAG are explicitly forbidden.** The "AustLII RAG" embedding service is unlawful.
- **Even manual access followed by AI processing is prohibited.** Policy 5(c) says restrictions apply "regardless of whether access [...] was obtained manually, programmatically, or through a combination."

### Lawful Alternatives

| Source | Access method | Cost | Coverage |
|--------|---------------|------|----------|
| **Federal Register of Legislation API** (`api.prod.legislation.gov.au`) | OData REST API, no auth, Swagger docs at `/swagger/index.html` | Free | Commonwealth legislation only (not case law) |
| **NSW Caselaw** (`caselaw.nsw.gov.au`) | Fetchable HTML, no API, no explicit AI ban found | Free | NSW courts/tribunals, 1999–present |
| **JADE / BarNet** (`jade.io`) | Has a limited API (3 endpoints per parse.bot); JADE Professional subscription | $95/mo or $995/yr | Australian case law + legislation; commercial terms apply |
| **High Court of Australia** (`hcourt.gov.au`) | Fetchable HTML | Free | HCA judgments only |
| **Federal Court** (`fedcourt.gov.au`) | Cloudflare-blocked (same issue as AustLII) | — | — |
| **Commercial: LexisNexis / Thomson Reuters** | Enterprise API with partnership | Custom ($$$) | Full AU case law + legislation + secondary materials |

**Recommendation:** Build citation verification on a combination of:
1. **Federal Register of Legislation API** for statute verification (free, lawful, machine-readable).
2. **JADE Professional subscription** ($95/mo) for case-law citation checking — has an API and commercial terms that permit programmatic use.
3. **NSW Caselaw** for NSW-specific judgments (check terms; fetch HTML, cache, parse — but verify their ToS doesn't have an AI clause).
4. **LexisNexis/Thomson Reuters API** for enterprise tier if budget allows.

Do NOT use AustLII for any automated, AI-related, or programmatic purpose.

---

## 2. Inference Architecture: Technically Impossible, Economically Irrational

### The Problem

The docs specify:
- Primary: SGLang server running **DeepSeek-V3** on **1× RunPod A100** ($1.43/hr)
- Fallback: vLLM running **Llama-3.1-70B**
- Cost: "RunPod A100, 500 hrs = $715/month"

### Why This Fails

**DeepSeek-V3** is a 671-billion-parameter Mixture-of-Experts model (37B active per token). Weight storage requirements:

| Precision | Weight size | Fits 1×A100-80GB? |
|-----------|------------|-------------------|
| bf16 | ~1,342 GB | No (needs ~17× A100) |
| FP8 | ~671 GB | No (needs ~8× H200-141GB) |
| INT4/Q4 | ~336 GB | No (needs ~5× A100) |

The DeepSeek-V3 model card itself recommends `torchrun --nnodes 2 --nproc-per-node 8` (16 GPUs) for inference. SGLang's recommended deployment uses FP8 with multi-GPU tensor parallelism.

**Llama-3.1-70B** (the "fallback") in bf16 needs ~140 GB — also doesn't fit on a single 80GB card. Only 4-bit quantization (~35 GB) fits, with tight KV-cache headroom.

**RunPod pricing (August 2026, verified from runpod.io/pricing):**
- A100 PCIe: $1.39/hr (not $1.43)
- A100 SXM: $1.59/hr
- H200 (141GB): $4.59/hr
- H100 PCIe: $2.89/hr
- H100 SXM: $3.29/hr

To actually serve DeepSeek-V3 on RunPod you'd need 8× H200 = ~$36.72/hr = ~**A$41,400/month** (reserved 24/7). That's **58× the documented $715/month**.

### The Solution: API-First Architecture

Per-case inference COGS via API is trivially cheap:

| Model | Input/1M | Output/1M | Per-case COGS (AUD) | Per-case COGS (USD) |
|-------|----------|-----------|---------------------|---------------------|
| gpt-oss-120b (OpenRouter) | $0.037 | $0.17 | A$0.06 | $0.04 |
| DeepSeek V4 Flash (OpenRouter) | $0.04 | $0.08 | A$0.07 | $0.05 |
| Qwen3-32B (OpenRouter) | $0.08 | $0.28 | A$0.10 | $0.07 |
| DeepSeek V3.2 (OpenRouter) | $0.26 | $0.38 | A$0.21 | $0.14 |
| DeepSeek V3.2 (Bedrock Sydney) | $0.64 | $1.91 | A$0.79 | $0.51 |
| Claude Sonnet 5 (Bedrock Sydney) | $2.00 | $10.00 | A$2.28 | $1.47 |
| Claude Opus 5 (Bedrock Sydney) | $5.00 | $25.00 | A$5.69 | $3.67 |

*(Per-case = ~206k input + ~32k output tokens for a 9-turn, 3-agent debate + doc draft + 20 citation checks. AUD≈1.55×USD.)*

Against a $49–149 price point, API inference is **0.04–4.6% of revenue**. Self-hosting breaks even only at hundreds of thousands of cases/month — far beyond any MVP target.

### Australian Data Residency — Solved

The docs worry about APP 8 cross-border disclosure with US-hosted inference. This is solvable with AU-region APIs:

| Provider | AU Region | Models Available | No-Training Guarantee |
|----------|----------|-------------------|----------------------|
| **AWS Bedrock** | ap-southeast-2 (Sydney) | DeepSeek V3.1/V3.2, Claude Sonnet 5, Claude Opus 5, gpt-oss-120b, Qwen3-235B, Llama, Mistral | Yes (Bedrock terms: customer data not used for training) |
| **Azure OpenAI** | Australia East | GPT models | Yes (Foundry terms: "NOT used to train any generative AI foundation models") |
| **Google Vertex AI** | australia-southeast1 (Sydney) | Claude Sonnet 5, Gemini models, DeepSeek (via ZAI) | Yes (Google Cloud data terms) |
| **OpenAI API** | au.api.openai.com (Sydney) | GPT models | Yes (with MAM/ZDR, Australia endpoint available) |

**Bedrock Sydney pricing (verified August 2026):**
- DeepSeek V3.2 Standard: $0.6386 input / $1.9055 output per 1M tokens
- gpt-oss-120b Standard: $0.1545 / $0.618
- Qwen3-235B Standard: $0.2266 / $0.9064
- Claude Sonnet 5: $2 / $10 (same as first-party Anthropic)
- Claude Opus 5: $5 / $25

**Recommendation:** Use **AWS Bedrock in Sydney** as primary inference. Start with **gpt-oss-120b** or **Qwen3-235B** for cost, **DeepSeek V3.2** for quality, and **Claude Sonnet 5** for premium/lawyer tier. All have AU data residency and no-training guarantees. No GPU management. No SGLang. No vLLM. No RunPod.

---

## 3. Court Rules Conflict: Affidavit Generation Is Prohibited

### The Problem

The docs list "Affidavit (witness statements)" as a supported document type for AI generation. **NSW Supreme Court Practice Note SC Gen 23 explicitly prohibits this.**

### Evidence

**Practice Note SC Gen 23** (issued 28 January 2025, commenced 3 February 2025, amended; full text retrieved from `supremecourt.nsw.gov.au`):

> **Para 10:** "Gen AI must not be used in generating the content of affidavits, witness statements, character references or other material that is intended to reflect the deponent or witness' evidence and/or opinion."

> **Para 12:** "Gen AI must not be used for the purpose of altering, embellishing, strengthening or diluting or otherwise rephrasing a witness's evidence."

> **Para 13:** "An affidavit, witness statement or character reference must contain a disclosure that Gen AI was not used in generating [its content]."

> **Para 17:** "Such verification [of citations] must not be solely carried out by using a Gen AI tool or program."

> **Para 20:** "Gen AI must not be used to draft or prepare the content of an expert report (or any part of an expert report) without prior leave of the Court."

Other jurisdictions have equivalent guidance:
- **Supreme Court of Queensland:** "Guidelines for Responsible Use by Non-Lawyers"
- **Supreme Court of Victoria:** "Guidelines for Litigants: Responsible Use of AI in Litigation"
- **New Zealand:** "Guidelines for use of generative AI in Courts and Tribunals"

Source: `supremecourt.nsw.gov.au/content/dcj/ctsd/supreme-court/supreme-court-home/practice-procedure/generative-artificial-intelligence.html`

### What This Means for LexSim

- **Remove affidavit generation** from the product. Gen AI-generated affidavits are prohibited in NSW SC and likely restricted in other jurisdictions.
- **Remove expert report generation.** Prohibited without court leave.
- **Citation verification must include human review.** Para 17 says AI-only verification is insufficient. The product must require the user (or a lawyer) to verify citations themselves — the tool can assist but cannot be the sole verifier.
- **Written submissions are permitted** (para 16) but require the author to verify all citations exist, are accurate, and are relevant — and this verification cannot be solely AI.
- **Gen AI can be used** for: chronologies, indexes, witness lists, briefs, summarising/reviewing documents and transcripts (para 9B). These are the safe product features.

### Revised Document Generator Scope

| Document type | Permitted? | Notes |
|---------------|-----------|-------|
| Statement of Claim | Yes (with citation caveat) | Written submission — permitted with human citation verification |
| Defence | Yes (with citation caveat) | Same |
| Affidavit / witness statement | **No** | Prohibited by SC Gen 23 para 10 |
| Expert report | **No** | Prohibited without court leave (para 20) |
| Subpoena request | Likely yes | Procedural document, not evidentiary |
| Discovery request | Likely yes | Procedural document |
| Court correspondence | Yes | Not evidentiary |
| Chronology / case summary | Yes | Explicitly permitted (para 9B(a)) |
| Document review / summarisation | Yes | Explicitly permitted (para 9B(c)) |

---

## 4. Legal Risk: UPL, Consumer Law, and Hallucinated Citations

### Unauthorised Practice of Law (UPL)

Under the **Legal Profession Uniform Law** (NSW, Vic, WA) and equivalent state legislation, only qualified, registered legal practitioners may engage in "legal practice" — which includes giving legal advice. The distinction between "legal information" and "legal advice" is critical:

- **Legal information** (permitted): "Here is the general test for negligence in Australia: duty of care, breach, causation, damage."
- **Legal advice** (restricted): "Based on your facts, you have a 65% chance of winning your negligence claim and should file in the Supreme Court."

LexSim's **outcome prediction** ("65% probability plaintiff wins") and **weakness report** ("Missing evidence for element 3 of negligence claim") are arguably legal advice, especially when delivered to unrepresented consumers who will reasonably rely on them.

Existing AU legaltech (Lawpath, Sprintlaw, Josef) position themselves as tools for lawyers or as legal information services with prominent disclaimers. None offer outcome prediction to consumers.

**DoNotPay precedent:** The FTC settled with DoNotPay in September 2024 for **$193,000** for "representing that its AI service could substitute for the services of a human lawyer" without testing or employing lawyers. Source: `ftc.gov/legal-library/browse/cases-proceedings/donotpay`.

While $193k is small, the reputational damage and the precedent are significant. Australia's **Australian Consumer Law** (ACL) sections 18 and 29 prohibit misleading and deceptive conduct and false representations. Marketing "70% accurate outcome prediction" without robust validation methodology could constitute misleading conduct.

### Australian AI Citation Hallucination Incidents

Two documented cases of Australian lawyers being sanctioned for AI-hallucinated citations:

1. **Valu v Minister for Immigration and Multicultural Affairs (No 2) [2025] FedCFamC2G 94** — A NSW practitioner ("the ALR") filed submissions citing **17 non-existent cases** and fabricated quotes from the AAT, generated by ChatGPT. Referred to the Office of the Legal Services Commissioner. The hearing had to be vacated. Source: `qlsproctor.com.au/2025/02/fake-cases-derail-lawyers-submissions/`

2. **Mr Dayal (Victorian lawyer, September 2025)** — First Australian lawyer formally sanctioned for AI-hallucinated citations. Stripped of ability to practise as a principal lawyer in the Federal Circuit and Family Court. Source: `theguardian.com/law/2025/sep/03/lawyer-caught-using-ai-generated-false-citations`

**Implication:** Citation verification is not a "nice to have" — it is a legal and professional obligation. But per SC Gen 23 para 17, AI-only verification is insufficient. The product must:
- Verify every citation against a lawful data source (JADE, FRL API, not AustLII)
- Flag unverified citations prominently
- Require explicit user acknowledgment before export
- Include a mandatory "AI Assistance Disclosure" statement in generated documents
- Never claim "verified" without human confirmation

---

## 5. Cost Model: Corrected

### Current (Documented) Cost Structure — 100 Active Users

| Component | Documented (AUD/mo) | Corrected (AUD/mo) | Notes |
|-----------|---------------------|--------------------|----|
| Frontend (Vercel Pro) | $20 | $20 | OK |
| Backend (Fly.io/Railway) | $50 | $50 | OK for MVP; overspecified architecture |
| Database (Supabase Pro) | $25 | $25 | OK |
| Redis (Upstash) | $10 | $10 | OK |
| **GPU Inference** | **$715** | **$50–400** | API-based, not self-host; depends on model tier |
| AustLII API | $0 | $95 | JADE Professional subscription (not AustLII) |
| Stripe fees | $150 | $150 | OK |
| SendGrid | $15 | $15 | OK |
| Twilio | $30 | $30 | OK |
| Auth (Clerk free tier) | $0 | $0 | Clerk free = 10k MAU; fine at 100 users |
| **PI Insurance** | **$0** | **$200–800** | Not in docs; essential for legal-adjacent product |
| **Legal/compliance review** | **$0** | **$100+** | Amortised; initial $5k noted in Next Steps |
| **Total** | **~$1,015** | **~$645–1,595** | |

### Per-Case COGS Breakdown

| Component | Cost (AUD) |
|-----------|-----------|
| LLM inference (9-turn debate + doc gen + citation checks) | $0.06–2.28 (model-dependent) |
| JADE API lookup (amortised) | ~$1.00 (at 90 cases/mo, $95 sub) |
| Stripe transaction fee (2.9% + $0.30) | ~$1.50–4.50 |
| SendGrid email | ~$0.01 |
| **Total per-case COGS** | **~$2.57–7.78** |

Against $49–149 price: **COGS is 1.7–16% of revenue**. Margin is genuinely high — but the documented **93% margin is overstated** because it omits insurance, legal review, support, refunds, and the "lawyer review add-on" cost (who pays the lawyer in the $299 tier?).

### Revenue Reality Check

The docs claim $15,910/month revenue at 100 users. Breakdown:
- 70 individual cases @ $99 avg = $6,930
- 20 lawyer subs @ $199 avg = $3,980
- 2 clinic enterprise @ $2,500 = $5,000

**Issues:**
- "70 individual cases" from 100 active users implies 70% of SRL users pay — optimistic for a new product with no brand trust.
- The $299 "premium with lawyer review add-on" requires a human lawyer marketplace — this is a separate business with its own UPL, insurance, and quality issues.
- Enterprise clinic sales ($2,500/mo) require SSO, audit logs, and procurement compliance — none are in the MVP.

---

## 6. Corporate Legal Team Suitability

### Current State: Not Ready

The docs target SRLs and solo/small firms. For corporate/in-house legal teams, the product would need:

| Requirement | Current status | Gap |
|-------------|---------------|-----|
| SSO/SAML/SCIM | Not in MVP (Phase 3 only) | Required for enterprise procurement |
| SOC 2 Type II / ISO 27001 | Not mentioned | Hard gate for most corporate legal departments |
| DMS integration (iManage, NetDocuments, SharePoint) | Not mentioned | Corporate legal teams live in their DMS |
| Audit logs (all AI inputs/outputs) | Listed in security checklist | Good start; needs exportable, tamper-evident format |
| RBAC with matter-level permissions | RLS by user only | Needs matter/team/firm hierarchy |
| DLP (data loss prevention) | Not mentioned | Required for privileged material |
| No-training guarantee | Mentioned for enterprise tier | Available via Bedrock/Azure/Vertex AU regions |
| Model risk documentation | Not mentioned | Corporate legal needs model cards, bias reports, evaluation methodology |
| Conflict checking | Not mentioned | Critical for any legal tool used in litigation |
| e-Billing / LEDES integration | Not mentioned | For lawyer/firm tier billing compliance |
| Vendor risk assessment | Not mentioned | Minter Ellison (AU law firm) guidance: "verify vendor governance, audit trails, and certifications (e.g. ISO/IEC 42001)" |

### Is the Product Concept Viable for Corporate Teams?

**Partially.** The multi-agent debate simulation is a genuinely novel feature that no major competitor offers:

- **Harvey** ($11B valuation, $190M ARR, 100k+ lawyers): Contract analysis, compliance, due diligence, litigation — but no courtroom simulation or outcome prediction. Pricing: $1,200–2,000/seat/mo.
- **CoCounsel** (Thomson Reuters, ex-Casetext, $650M acquisition): AI legal assistant for research, drafting, review. $225–400/seat/mo. No debate simulation.
- **Lexis+ AI / Protégé**: Legal research + agentic workflows. $250–500/seat/mo. No outcome prediction.
- **Spellbook** ($50M Series B): Contract review/drafting. No litigation simulation.
- **Legora** ($5.55B valuation): Collaborative AI for lawyers. No courtroom simulation.
- **Blue J** (tax): Outcome prediction for tax — closest analogue to LexSim's prediction concept. But tax-specific, not litigation.
- **Lex Machina**: Litigation analytics (judge/court/party statistics) — data-driven, not AI-simulated. No argument simulation.

**The whitespace:** No major legal AI product offers **multi-agent adversarial argument simulation with outcome prediction**. This is genuinely novel. The question is whether it's useful enough that people will pay for it.

**For corporate legal teams specifically:** Litigation strategy simulation could be valuable for in-house teams evaluating whether to settle vs. litigate, or for trial preparation. But it would need to be positioned as a **decision-support tool for lawyers**, not as a consumer product, and would require all the enterprise procurement features above.

---

## 7. Architecture Recommendations

### MVP: Simplify Radically

The documented architecture (Next.js + FastAPI + Celery + Redis + WebSocket server + Kong API Gateway + SGLang + vLLM + BGE-M3 + multi-cloud) is over-engineered for a 6-week, 10-user MVP.

**Recommended MVP stack:**

```
┌─────────────────────────────────────────────┐
│  Frontend: Next.js 14 (Vercel)              │
│  - App Router, Server Components            │
│  - shadcn/ui                                │
│  - Server-Sent Events for debate streaming  │
│    (simpler than WebSocket for MVP)          │
└──────────────────────────┬──────────────────┘
                           │ REST + SSE
                           ▼
┌─────────────────────────────────────────────┐
│  Backend: FastAPI monolith (single process) │
│  - JWT auth (Clerk)                         │
│  - Supabase Postgres (RLS)                   │
│  - Background tasks: FastAPI BackgroundTasks  │
│    or arq (lightweight, Redis-based)         │
│    (NOT Celery for MVP)                      │
│  - LLM calls via AWS Bedrock SDK             │
│  - Citation verification via JADE + FRL API │
└──────────────────────────┬──────────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Supabase │ │ Upstash  │ │ AWS      │
│ Postgres │ │ Redis    │ │ Bedrock  │
│ (RLS)    │ │ (cache)  │ │ (Sydney) │
└──────────┘ └──────────┘ └──────────┘
```

**What to drop from MVP:**
- Celery → use FastAPI BackgroundTasks or arq (Redis-based, simpler)
- WebSocket server → SSE is simpler and sufficient for debate streaming
- Kong/AWS API Gateway → Vercel + FastAPI direct is fine for MVP
- SGLang + vLLM + GPU hosting → AWS Bedrock API
- BGE-M3 embedding service → JADE API + FRL API for verification (no vector search needed initially)
- Separate AI orchestrator service → embed in FastAPI

**What to add:**
- Citation verification against JADE + FRL API (not AustLII)
- Human-in-the-loop citation confirmation step (per SC Gen 23 para 17)
- AI disclosure statement auto-generation for court filings
- Plain-language mode for SRLs (simplified output, glossary)
- Calibration/uncertainty display (show confidence intervals, not point estimates)

### Auth Fix

The docs use `auth.uid()` in Supabase RLS policies, but auth is Auth0/Clerk. **This will not work** — `auth.uid()` is a Supabase Auth helper that returns NULL for external JWTs.

**Fix:** Either:
1. Use **Supabase Auth** (drop Auth0/Clerk) — simplest, `auth.uid()` works natively, and Supabase Auth supports email/password + OAuth.
2. Use **Clerk + Supabase** with custom JWT claims — Clerk issues JWTs with `sub` claim; configure Supabase to use `request.jwt.claims.sub` in RLS policies instead of `auth.uid()`.

Option 1 is simpler for MVP. Option 2 is better if you need Clerk's advanced features (organizations, SSO for enterprise tier).

---

## 8. UX Improvements for SRLs

### SRL Market Context

- **30–40% of Family Court of Australia matters** involve self-represented litigants at some point. Source: Productivity Commission, *Access to Justice Arrangements* report.
- Very few Australian jurisdictions keep detailed SRL statistics. Source: IAJ-UIM, *Self-Represented Litigants in Australia* (2025).
- SRLs skew toward lower income, lower legal literacy, and higher emotional stress.

### Recommended UX Features

1. **Plain-language mode**: All AI output should have a "plain English" toggle that rewrites legal reasoning in simple language with a glossary. SRLs don't understand "prima facie", "force majeure", "stare decisis".

2. **Guided intake wizard**: Step-by-step with plain-language questions, not legal jargon. "What happened?" not "State your cause of action."

3. **Uncertainty communication**: Instead of "65% probability plaintiff wins", show a range with context: "This case has mixed prospects. Similar cases succeed about 60–70% of the time, but your missing evidence for [X] could lower this. This is not a prediction of your actual outcome."

4. **What-this-means panel**: After each debate turn, show a "What this means for you" summary in plain language.

5. **Action checklist**: Instead of just a "weakness report", generate a checklist: "To strengthen your case: 1. Get a written statement from [witness], 2. Obtain [document], 3. Consider filing in [court] by [date]."

6. **Trust calibration**: Show limitations prominently. "This is an AI simulation, not legal advice. It cannot predict your actual court outcome. Consult a lawyer for advice about your case."

7. **Accessibility**: WCAG 2.1 AA compliance. Many SRLs have disabilities. Screen reader support, keyboard navigation, high contrast.

8. **Mobile-first responsive design**: SRLs are more likely to use phones than laptops.

9. **Emotional support**: SRLs are often in stressful situations (family breakdown, eviction, debt). A calm, supportive UI tone matters. Avoid aggressive "opponent" language in the UI.

---

## 9. Document-Internal Issues

| Issue | Location | Fix |
|-------|----------|-----|
| "7-turn protocol" but lists 9 turns | REQUIREMENTS.md | Standardise on "9-turn" or restructure to 7 |
| `auth.uid()` with Auth0/Clerk | REQUIREMENTS.md RLS | Use Supabase Auth or Clerk JWT claims |
| `CREATE INDEX idx_simulations_user_id ON simulations(user_id)` | REALTIME_COURTROOM.md | `simulations` has no `user_id` column; index on `case_id` |
| `Column(Float)` without import | ARCHITECTURE.md | Import `Float` from sqlalchemy |
| `VoiceNot Enabled` (space in name) | REALTIME_COURTROOM.md | `VoiceNotEnabled` |
| Redis: Upstash (costs) vs ElastiCache (prod) | REQUIREMENTS.md vs ARCHITECTURE.md | Pick one; Upstash for MVP, ElastiCache for scale |
| WS path: `/ws/simulation/{id}` (FE) vs `/api/v1/simulations/{id}/stream` (API) | REALTIME_COURTROOM.md vs ARCHITECTURE.md | Standardise on one path |
| Guest tier in intervention table but not in pricing | REALTIME_COURTROOM.md vs REQUIREMENTS.md | Add guest tier to pricing or remove from intervention table |
| TTS quota: "5,000 tokens ≈ 30 min audio" | REALTIME_COURTROOM.md | 30 min speech ≈ 27,000–30,000 chars; ElevenLabs charges per character. Quota is ~6× overstated. |
| VoiceControl uses browser SpeechSynthesis (free) but product charges $29 for "voice" | REALTIME_COURTROOM.md | Either the free browser API is the implementation (remove charge) or ElevenLabs is the backend (fix the code) |
| "Admin dashboard (lawyer/clinic tiers)" | ARCHITECTURE.md | Admin should be internal staff, not lawyers/clinics |

---

## 10. Revised Roadmap

### Phase 1: Legal-Compliant MVP (8 weeks)

1. **Week 1–2:** Auth (Supabase Auth or Clerk), case intake wizard (plain-language), document upload
2. **Week 3–4:** Multi-agent debate engine (3 agents, 9-turn, via AWS Bedrock Sydney)
3. **Week 5:** Citation verification via JADE API + FRL API (NOT AustLII); human-in-the-loop confirmation
4. **Week 6:** Document generator (statement of claim, defence, court correspondence — NOT affidavits); AI disclosure statement
5. **Week 7:** Stripe billing, plain-language output mode, uncertainty communication
6. **Week 8:** Security hardening, APP compliance checklist, beta onboarding for 5 SRLs

**What's explicitly NOT in MVP:**
- Affidavit/expert report generation (prohibited by court rules)
- Voice features (not justified for MVP; browser Web Speech API is free if needed)
- Real-time courtroom viewer with WebSocket (use SSE or simple polling)
- Witness/expert agents
- Mobile app
- Enterprise/clinic tier with SSO
- Self-hosted GPU inference

### Phase 2: Production Launch (6 weeks)

1. Deadline calculator + calendar integration
2. Lawyer subscription tier + dashboard
3. Judge reasoning quality improvements (prompt engineering, calibration testing)
4. Legal review: engage Australian tech lawyer for APP/LPP/UPL compliance audit
5. PI insurance procurement
6. Public beta ($49/case)

### Phase 3: Enterprise & Corporate (10 weeks)

1. SSO/SAML, SCIM, audit log export
2. SOC 2 Type II certification process
3. DMS integration (iManage, NetDocuments, SharePoint)
4. Matter-level RBAC + conflict checking
5. Enterprise/clinic tier
6. Corporate legal team pilot (litigation strategy simulation for in-house counsel)
7. Optional: voice features (only if user demand justifies the cost and complexity)

### Phase 4: Scale (ongoing)

1. Witness/expert agents
2. Mobile-responsive web app (not React Native)
3. Court eFiling integration (per jurisdiction)
4. Model evaluation framework (calibration, accuracy tracking, bias testing)
5. Self-hosted inference (only when volume > 10k cases/month justifies it)

---

## 11. Summary of Recommendations

| Area | Current | Recommended | Priority |
|------|---------|-------------|----------|
| **Citation data source** | AustLII API (doesn't exist, unlawful) | JADE Professional + FRL API | **Critical** |
| **Inference** | Self-host SGLang DeepSeek-V3 on 1×A100 | AWS Bedrock Sydney API (gpt-oss-120b / DeepSeek V3.2 / Claude) | **Critical** |
| **GPU cost** | $715/mo (impossible) | $50–400/mo API usage-based | **Critical** |
| **Affidavit generation** | Listed as feature | Remove (prohibited by SC Gen 23) | **Critical** |
| **Citation verification** | AI-only via AustLII | AI-assisted + human confirmation via JADE/FRL | **Critical** |
| **Outcome prediction** | Point estimate "65%" | Range + context + "not legal advice" disclaimer | **High** |
| **Architecture** | Microservices + Celery + WS + Kong | FastAPI monolith + SSE + Bedrock API | **High** |
| **Auth** | Auth0/Clerk + `auth.uid()` (broken) | Supabase Auth, or Clerk + JWT claims | **High** |
| **Voice features** | MVP feature ($29 add-on) | Defer to Phase 3+ | **Medium** |
| **Corporate readiness** | Not in MVP | Phase 3: SSO, SOC 2, DMS, RBAC | **Medium** |
| **PI insurance** | Not in cost model | Add $200–800/mo | **Medium** |
| **SRL UX** | Legal jargon, point predictions | Plain-language, ranges, glossary, checklist | **Medium** |
| **Doc consistency** | Multiple internal contradictions | Fix per section 9 table | **Low** |

---

*This review is based on web research conducted 26 August 2026 using DuckDuckGo and Mojeek search, primary-source verification of court practice notes, vendor pricing pages, and HuggingFace model cards. All prices and facts are as of that date.*
