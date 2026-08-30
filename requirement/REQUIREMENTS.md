# LexSim AI — Legal Simulation SaaS Platform

> **⚠️ PARTIALLY SUPERSEDED (30 Aug 2026) — check TECH_STACK.md v2 before scaffolding.**
> Still valid: product vision, features, pricing, compliance rules, roadmap.
> STALE — do not copy: the SQL schema block (uses `clerk_user_id` + Clerk-JWT `auth.uid()` policy — scaffolding from it regresses the RLS fix) and tech-architecture blocks naming Clerk, Celery, WebSocket, OpenRouter primary, and AustLII-adjacent sources. Build from `TECH_STACK.md` (Supabase Auth model) + `TEST_PLAN.md` instead.

## Product Vision
**Multi-agent legal debate simulation platform** for self-represented litigants (SRLs) and solo practitioners in Australia. Simulates courtroom adversarial proceedings to predict case outcomes, identify weaknesses, and generate court-ready documents with verified citations.

---

## ⚠️ Compliance Disclaimers (Mandatory)

### NSW Supreme Court Practice Note SC Gen 23 Compliance
- ✅ **Allowed:** Chronologies, document review, written submissions, case preparation
- ❌ **Prohibited:** Affidavits, witness statements, evidentiary material (Para 10)
- ✅ **Required:** Citation verification must include human review (Para 17)
- ✅ **Required:** User attestation before filing any AI-assisted document

### DoNotPay Precedent Warning
> "LexSim does not replace legal advice. This tool provides simulation and preparation assistance only. You remain responsible for all court filings."

### Legal Professional Privilege (LPP) Warning
> "AI analysis may not be privileged. Do not input confidential client communications without consulting a lawyer."

---

## Target Users

| Segment | Pain Point | Willingness to Pay |
|---------|------------|-------------------|
| **Solo Practitioners** (Primary) | Overwhelmed by document drafting, need second-opinion on case strategy | $99-499/month subscription |
| **Self-Represented Litigants** (Secondary) | Can't afford lawyers ($300-800/hr), risk hallucinated AI submissions getting case dismissed | $49-149 per case |
| **Legal Aid Clinics** (Enterprise) | High volume of pro bono cases, limited staff time per client | $2k-5k/month |

---

## Core Features (MVP v1.0)

### 1. Authentication & Multi-Tenancy
- **User Roles:**
  - `individual` (SRL, pay-per-case)
  - `lawyer` (solo/small firm, subscription)
  - `clinic` (legal aid, enterprise)
- **Authentication:** Email/password + Google OAuth (Clerk.dev)
- **Data Isolation:** Row-level security (RLS) in PostgreSQL — each user sees only their cases
- **Compliance:** Australian Privacy Principles (APP) compliant data handling
- **Data Residency:** All data stored in AWS ap-southeast-2 (Sydney)

### 2. Case Intake Workflow
1. **Upload Documents:** PDF/DOCX (contracts, emails, court notices, evidence)
2. **Timeline Builder:** Drag-and-drop interface to sequence events
3. **Party Identification:** Auto-extract plaintiff/defendant/witnesses from documents
4. **Cause of Action Selector:** Dropdown mapped to Australian law (contract breach, negligence, defamation, employment, family law, tenancy)
5. **Jurisdiction Selector:** Federal Court, Supreme Court (NSW/VIC/QLD/etc.), Local Court, Tribunal (NCAT, VCAT, QCAT)
6. **Compliance Attestation:** User confirms "I have reviewed all AI-generated content" (NSW SC Gen 23)

### 3. Multi-Agent Debate Simulation
**Architecture:**
```
┌─────────────────────────────────────────────────────────────┐
│  Simulation Engine (3 LLM agents, 9-turn debate protocol)   │
├─────────────────────────────────────────────────────────────┤
│  Agent 1: USER_ADVOCATE — argues your position              │
│  Agent 2: OPPONENT — adversarial counter-arguments          │
│  Agent 3: JUDGE — neutral adjudicator, tracks belief state  │
└─────────────────────────────────────────────────────────────┘
```

**Debate Protocol (9-turn structured):**
1. Plaintiff opening statement
2. Defendant opening statement
3. Judge initial belief update (confidence %, key issues)
4. Plaintiff rebuttal
5. Defendant rebuttal
6. Judge mid-debate belief update
7. Plaintiff closing
8. Defendant closing
9. **Judge final verdict** (outcome prediction + confidence + reasoning)

**Output:**
- **Outcome Prediction:** "65% probability plaintiff wins"
- **Weakness Report:** "Missing evidence for element 3 of negligence claim"
- **Debate Transcript:** Full searchable log (exportable PDF)
- **Judge's Reasoning:** Point-by-point analysis of strongest/weakest arguments

### 4. Document Generator with Citation Verification
**⚠️ NSW SC Gen 23 Restrictions:**
- ✅ **Allowed:** Written submissions, chronologies, correspondence
- ❌ **Prohibited:** Affidavits, witness statements, evidentiary material

**Supported Documents:**
- Statement of Claim
- Defence
- Written Submissions
- Chronology of Events
- Court correspondence

**Citation Verification Pipeline:**
1. Agent generates draft with case citations
2. **Verification Agent** queries NSW Caselaw API + Federal Register of Legislation
3. Flags: ❌ Fake case, ⚠️ Unverified, ✅ Verified
4. **Human Review Required:** User must confirm all citations (NSW SC Gen 23 Para 17)
5. **Hallucination Score:** 0-100% risk rating before export
6. **Attestation:** "I have reviewed all citations against authoritative sources"

### 5. Deadline Calculator
- Auto-compute response deadlines based on document type + jurisdiction
- Handle weekends/public holidays per state
- Calendar integration (Google Calendar, Outlook iCal export)
- Email reminders (SendGrid)

### 6. Pricing & Billing
- **Pay-per-case (Individual):** $49 (basic) / $149 (simulation + documents)
- **Subscription (Lawyer):** $99/month (10 cases) / $299/month (unlimited)
- **Enterprise (Clinic):** Custom pricing, SSO, audit logs
- **Payment Gateway:** Stripe (AUD, GST-compliant invoicing)

---

## Technical Architecture

### High-Level Stack
```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Next.js 14 + TypeScript + Tailwind CSS)          │
│  - App Router, Server Components                            │
│  - shadcn/ui components                                     │
│  - React Hook Form + Zod validation                         │
│  - PDF.js for document preview                              │
│  - WebSocket client for live debate streaming               │
│  - Web Speech API (free TTS/STT)                            │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ (REST/GraphQL)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Backend (FastAPI + Python 3.11)                            │
│  - JWT authentication (Clerk.dev)                           │
│  - PostgreSQL (Supabase) with Row-Level Security            │
│  - Redis (cache, rate limiting, session store)              │
│  - Celery + Redis (async task queue for simulations)        │
│  - WebSocket server (FastAPI WebSocket)                     │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ (HTTP)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  AI Orchestrator (Custom NEXUS-style framework)             │
│  - Agent role prompts (plaintiff/defendant/judge)           │
│  - Debate state machine (9-turn protocol)                   │
│  - Citation verification module (NSW Caselaw + FRL API)     │
│  - Document generation templates (Jinja2)                   │
│  - Pause/resume/intervention handler                        │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ (HTTP)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Inference Layer                                            │
│  - Primary: OpenRouter API (gpt-oss-120b)                   │
│  - Fallback: AWS Bedrock Sydney (gpt-oss-120b)              │
│  - Embedding: BGE-M3 (NSW Caselaw RAG)                      │
│  - Cost: ~$0.06 AUD per case (OpenRouter)                   │
└─────────────────────────────────────────────────────────────┘
                          │
                          │ (REST)
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  External APIs                                              │
│  - NSW Caselaw (case law search, citation verification)     │
│  - Federal Register of Legislation API (Commonwealth law)   │
│  - Stripe (payments)                                        │
│  - SendGrid (transactional emails)                          │
│  - Clerk.dev (authentication)                               │
└─────────────────────────────────────────────────────────────┘
```

### Database Schema (PostgreSQL)
```sql
-- Users (managed by Clerk.dev, mirrored locally)
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  clerk_user_id TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE NOT NULL,
  role TEXT CHECK (role IN ('individual', 'lawyer', 'clinic')) NOT NULL,
  subscription_tier TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Cases
CREATE TABLE cases (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  jurisdiction TEXT NOT NULL,
  cause_of_action TEXT NOT NULL,
  status TEXT CHECK (status IN ('intake', 'simulating', 'completed', 'archived')) DEFAULT 'intake',
  simulation_paused BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Documents (uploaded evidence)
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
  file_path TEXT NOT NULL,
  file_type TEXT NOT NULL,
  uploaded_at TIMESTAMPTZ DEFAULT NOW()
);

-- Simulation Results
CREATE TABLE simulations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
  debate_transcript JSONB NOT NULL,
  outcome_prediction JSONB NOT NULL,
  weakness_report JSONB,
  interventions JSONB DEFAULT '[]'::jsonb,
  pause_history JSONB DEFAULT '[]'::jsonb,
  hallucination_score FLOAT CHECK (hallucination_score BETWEEN 0 AND 1),
  user_attestation BOOLEAN DEFAULT FALSE, -- NSW SC Gen 23 compliance
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Generated Documents
CREATE TABLE generated_documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
  simulation_id UUID REFERENCES simulations(id),
  doc_type TEXT NOT NULL,
  content TEXT NOT NULL,
  citations_verified JSONB,
  user_reviewed BOOLEAN DEFAULT FALSE, -- NSW SC Gen 23 Para 17
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Deadlines
CREATE TABLE deadlines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
  trigger_doc_type TEXT NOT NULL,
  due_date DATE NOT NULL,
  reminder_sent BOOLEAN DEFAULT FALSE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Row-Level Security (RLS) Policies
ALTER TABLE cases ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON cases
  USING (user_id = auth.uid());
```

---

## Compliance & Security Requirements

### Australian Privacy Principles (APP) Compliance
1. **Data Residency:** All data stored in AWS ap-southeast-2 (Sydney)
2. **Encryption:** AES-256 at rest, TLS 1.3 in transit
3. **Access Controls:** Role-based access control (RBAC), MFA for lawyer accounts
4. **Data Retention:** Auto-delete cases after 7 years (statute of limitations)
5. **Breach Notification:** Automated OAIC notification workflow if breach detected
6. **Cross-Border Disclosure:** OpenRouter/AWS Bedrock have APP-equivalent DPAs

### NSW Supreme Court Practice Note SC Gen 23
1. **Document Restrictions:** Block affidavit/witness statement generation
2. **Citation Verification:** Require human review (not solely AI)
3. **User Attestation:** "I have reviewed all AI-generated content"
4. **Disclaimer:** "This document was prepared with AI assistance"

### Legal Professional Privilege (LPP) Protection
- **Warning:** "AI analysis may not be privileged. Consult a lawyer for privileged advice."
- **Audit logs:** Track all AI inputs/outputs for potential LPP disputes
- **No data logging:** Configure OpenRouter/Bedrock to not store prompts/responses

### DoNotPay Precedent Compliance
- **Disclaimer:** "LexSim does not replace legal advice"
- **No unsubstantiated claims:** Never claim "AI will win your case"
- **Clear limitations:** "Simulation provides preparation assistance only"

---

## Development Roadmap

### Phase 1: MVP (6 weeks)
- [ ] Week 1-2: Auth (Clerk) + Case Intake + Document Upload
- [ ] Week 3-4: Multi-Agent Debate Engine (3 agents, 9-turn protocol)
- [ ] Week 5: NSW Caselaw + Federal Register Integration (citation verification)
- [ ] Week 6: Document Generator (NSW SC Gen 23 compliant) + Stripe Integration
- **Launch:** Beta for 10 solo lawyers (free pilot)

### Phase 2: Production (4 weeks)
- [ ] Week 7: Deadline Calculator + Calendar Integration
- [ ] Week 8: Lawyer Subscription Tier + Dashboard
- [ ] Week 9: Enhanced Prompts + Judge Reasoning Quality
- [ ] Week 10: Security Audit + APP Compliance Review
- **Launch:** Public beta ($49/case, $99/mo lawyer tier)

### Phase 3: Scale (8 weeks)
- [ ] Week 11-12: Real-Time Courtroom Viewer (WebSocket streaming)
- [ ] Week 13-14: Pause/Intervention System
- [ ] Week 15-16: Free Browser TTS/STT (Web Speech API)
- [ ] Week 17-18: Enterprise (Legal Aid Clinics) + SSO
- **Launch:** Full SaaS + Enterprise Sales

---

## Cost Structure (Monthly, 100 Active Users)

| Component | Cost (AUD) |
|-----------|------------|
| **Frontend Hosting** (Vercel Pro) | $20 |
| **Backend** (Fly.io / Railway) | $50 |
| **Database** (Supabase Pro) | $25 |
| **Redis** (Upstash) | $10 |
| **Inference** (OpenRouter, 100 cases × $0.06) | $6 |
| **NSW Caselaw** (Free) | $0 |
| **Federal Register API** (Free) | $0 |
| **Stripe Fees** (2.9% + $0.30/txn) | ~$150 |
| **SendGrid** (10k emails) | $15 |
| **Clerk.dev** (1k MAU free) | $0 |
| **Total** | **~$276/month** |

**Revenue @ 100 users:**
- 50 individual cases @ $99 avg = $4,950
- 30 lawyer subs @ $199 avg = $5,970
- 3 clinic enterprise @ $2,500 = $7,500
- **Total Revenue:** $18,420/month
- **Profit Margin:** ~98.5%

---

## Go-to-Market Strategy

### Distribution Channels
1. **Law Society Partnerships:** NSW Law Society, Victorian Bar Association
2. **SEO:** Target "solo lawyer AI assistant", "case outcome prediction Australia"
3. **Content Marketing:** Blog on "NSW SC Gen 23 compliance", "AI in Australian courts"
4. **Referrals:** Lawyer referral program (20% commission on first 3 months)

### Risk Mitigation
| Risk | Mitigation |
|------|------------|
| **Hallucinated citations get user sanctioned** | NSW Caselaw verification + human review attestation + $1M professional indemnity insurance |
| **LPP waiver claims** | Clear warnings + audit logs + enterprise data isolation |
| **Court rejects AI-generated docs** | NSW SC Gen 23 compliance + disclosure statement generator |
| **AustLII blocks access** | Already using NSW Caselaw + Federal Register (no AustLII dependency) |

---

## Success Metrics (First 12 Months)
- **Users:** 500 active (200 SRL, 250 lawyers, 5 clinics)
- **Revenue:** $75k MRR
- **Case Outcomes:** Track user-reported win rates vs simulation predictions (target: 70% accuracy)
- **NPS:** >50 (legal tech benchmark: 35)
- **Churn:** <5% monthly (lawyer tier), <15% (individual)

---

## Next Steps
1. **Validate:** Interview 10 solo lawyers (confirm willingness to pay, NSW SC Gen 23 compliance)
2. **Prototype:** Build MVP debate engine (3 agents, NSW Caselaw integration) — 2 weeks
3. **Legal Review:** Engage Australian tech lawyer for APP/LPP/NSW SC compliance audit — $5k
4. **Incorporate:** Pty Ltd company, ABN, GST registration
5. **Beta Launch:** 10 free pilot users (lawyers only) → iterate → public launch

**This document is the single source of truth for LexSim AI development.**
