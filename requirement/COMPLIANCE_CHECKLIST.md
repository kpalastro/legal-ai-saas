# LexSim AI — Compliance Control Checklist (v1.0, Aug 2026)

Maps every compliance requirement from `REQUIREMENTS.md` §Compliance & Security to its **implementation point** in the v2.1 stack (`TECH_STACK.md`), so @coderbot builds each control in rather than bolting it on. Each control is testable on the localhost v1 stack.

Legend: **Stage** = when it must exist (S1 = first scaffold, S2 = debate engine, S3 = doc gen/export, S4 = pre-launch).
**Verify-on-localhost** = how @testing proves it works without any cloud dependency.

---

## 1. NSW SC Gen 23 (courts: AI-generated documents)

| # | Control | Requirement source | Implementation point | Stage | Verify-on-localhost |
|---|---------|--------------------|----------------------|-------|---------------------|
| 1.1 | No affidavit / witness-statement / expert-report generation | SC Gen 23 para 10/20 | `apps/api/app/documents/` registry contains **no such template**; doc-type allowlist in code + UI hides them for AU jurisdictions. An API request for a banned doc type returns `403 DOCUMENT_TYPE_PROHIBITED` | S3 | pytest: request banned doc_type → 403; Playwright: selector absent from doc-gen UI |
| 1.2 | Mandatory human citation-confirmation gate before export | SC Gen 23 para 17 | DB CHECK `generated_documents` export requires every citation row `status='verified'` AND `user_reviewed=true`. Gate enforced in the **export service** (server-side), not just UI | S3 | pytest: fake citation with `verified=false` → export 403 with the offending citation id |
| 1.3 | User attestation before any AI-assisted document leaves the system | SC Gen 23 | `simulations.user_attestation` + `generated_documents.user_reviewed`; export blocked unless BOTH true | S3 | pytest: attestation=false → export 403; UI shows attestation checkbox pre-export |
| 1.4 | Auto AI-disclosure footer on every generated document | SC Gen 23; REQUIREMENTS disclaimer | Jinja2 base template injects fixed "This document was prepared with AI assistance" block — **not removable by prompt or template param** | S3 | pytest: every generated doc HTML/DOCX contains the disclosure string |
| 1.5 | "Not legal advice" + calibrated range copy on outcome predictions | ACL s18/s29 (misleading conduct) | Prediction API returns `{lower, point, upper, methodology_note}`; UI renders range + disclaimer, never a bare "65% you win" | S2 | pytest: response schema excludes bare point-estimate field; snapshot test of the verdict card |
| 1.6 | Allowed-document scope only: Statement of Claim, Defence, Written Submissions, Chronology, Correspondence | SC Gen 23 | Template registry allowlist matches REQUIREMENTS.md §4 exactly | S3 | pytest: registry contents == allowlist constant |

## 2. Australian Privacy Principles (APP)

| # | Control | Requirement source | Implementation point | Stage | Verify-on-localhost |
|---|---------|--------------------|----------------------|-------|---------------------|
| 2.1 | Data residency: ap-southeast-2 only | APP 8 / APP 11 | v1: everything localhost (n/a). Prod: Bedrock client pinned `region_name='ap-southeast-2'`; config test **fails startup** if `LLM_PROVIDER=bedrock` with a non-Sydney region | S4 | pytest with mocked boto3: wrong region → startup ValidationError |
| 2.2 | Encryption at rest / TLS in transit | APP 11 | Postgres volume encryption in compose (prod: Supabase/RDS default); TLS via reverse proxy in prod. Localhost: document why it's exempt in `.env.example` comment | S4 | config review |
| 2.3 | RBAC + MFA on lawyer accounts | APP security | Supabase Auth (GoTrue) roles: `individual`/`lawyer`/`clinic`; MFA optional v1, enforced at clinic tier Phase 3 | S1 | Playwright: role-scoped dashboard redirects |
| 2.4 | 7-year retention auto-delete | APP 11.2 | arq cron job `purge_expired_cases` (daily): deletes cases + documents + simulations older than 7y; **sturdy idempotent**; audit-log rows retained (de-identified) | S2 | pytest: seed old case → run job → case gone, audit rows intact |
| 2.5 | OAIC breach-notification workflow | APP / NDB scheme | `audit_log` anomaly alert → SendGrid/Mailpit workflow doc `infra/breach_response.md` (roles, 30-day assessment clock, OAIC form link) | S4 | checklist review only |
| 2.6 | Cross-border disclosure register | APP 8 | `infra/data_flows.md`: one row per external processor (v1: none; prod: AWS Bedrock Sydney, Stripe, SendGrid) with DPA/PB (Privacy Binding) reference | S4 | doc review |
| 2.7 | Collection notice + consent at signup | APP 5 | Signup screen states what is collected, that AI (model named per provider) processes case content, and the LPP warning | S1 | Playwright: notice present before account creation |

## 3. Legal Professional Privilege (LPP)

| # | Control | Requirement source | Implementation point | Stage | Verify-on-localhost |
|---|---------|--------------------|----------------------|-------|---------------------|
| 3.1 | LPP warning before document/case-content input | REQUIREMENTS LPP section | Interstitial warning on first case creation + footer in every doc | S1 | Playwright: warning shown once per account |
| 3.2 | Append-only audit log of all AI inputs/outputs | LPP disputes trail | `audit_log` table (id, ts, user_id, case_id, event, model, prompt_sha, response_sha, token counts, **content_ref**) stored in-process. **Hashes are tamper-evidence, not the trail:** an LPP dispute requires reconstructing what was actually sent/received, so v1 (local-only, cheapest place we will ever store this) keeps the full prompt/response text in a local `audit_content` store referenced by `content_ref`; hashes prove it hasn't been altered. Prod decision (S4, with @security): retention window for `audit_content` + whether it stays local or moves to an encrypted Sydney S3 bucket. **No UPDATE/DELETE grants**; app role has INSERT/SELECT only. Bedrock model invocation logging (prod) → Sydney-only S3/CloudWatch | S2 | pytest: app DB role lacks UPDATE/DELETE on audit_log; audit row for a simulated turn resolves via content_ref to the exact prompt/response |
| 3.3 | Do-not-store prompts/responses at providers | REQUIREMENTS | v1: Ollama is local — nothing leaves the machine (optimal prod posture too); prod Bedrock: no prompt/response logging enabled, invocation log = metadata only. Documented in `infra/data_flows.md` | S4 | curl Ollama: confirm no history endpoint used; config review for Bedrock flags |

## 4. DoNotPay Precedent (misleading-conduct / UPL hygiene)

| # | Control | Requirement source | Implementation point | Stage | Verify-on-localhost |
|---|---------|--------------------|----------------------|-------|---------------------|
| 4.1 | Global disclaimer: "does not replace legal advice" | REQUIREMENTS | Persistent banner + on every simulation verdict + pricing page | S1 | Playwright: banner present on dashboard |
| 4.2 | No unsubstantiated claims ("AI will win your case" etc.) | REQUIREMENTS | Copy review lint: banned-phrase list in CI (`scripts/check_marketing_copy.py`) scanning FE strings + docs | S4 | CI job: banned phrase → fail |
| 4.3 | Citation-hallucination risk surfaced to user | Lawyers sanctioned for fake citations | Hallucination score (0–100) shown next to every generated doc; docs with score > threshold require per-citation review, not bulk confirm | S3 | pytest: score threshold toggles per-citation review requirement |

## 5. Multi-Tenancy / Security Foundations

| # | Control | Requirement source | Implementation point | Stage | Verify-on-localhost |
|---|---------|--------------------|----------------------|-------|---------------------|
| 5.1 | RLS `user_id = auth.uid()` on cases/documents/simulations/deadlines | REQUIREMENTS schema | **Scaffold from Supabase Auth model — do NOT copy the `clerk_user_id` DDL in REQUIREMENTS.md.** `users.id UUID REFERENCES auth.users(id)`; RLS policies on every case-bearing table; app DB role has `BYPASSRLS=false` | S1 | pytest (self-hosted GoTrue): user A sees 0 rows of user B's cases; live `EXPLAIN` shows policy applied |
| 5.2 | Attestation + citation gate cannot be bypassed via API | SC Gen 23 | Export endpoint re-checks DB state server-side; no client-trusted flags | S3 | pytest: forge `user_reviewed=true` in request body → ignored, gate still applies |
| 5.3 | Provider abstraction never leaks data across providers | APP 8 (preparedness) | `llm/` adapter contract: no provider sees data another didn't send; Bedrock adapter hard-codes Sydney region + no-training providers; unit test both adapters with the same fixture transcript | S2 | pytest: `LLM_PROVIDER=ollama` vs mock-bedrock produce byte-identical audit_log event shapes |

## 6. CI Gates (add to `.github/workflows/ci.yml`)

- `pytest -m compliance` marker: all controls above tagged `@pytest.mark.compliance`; this suite **cannot be skipped** on PRs touching `documents/`, `export`, `rls`, or `audit`.
- Banned-doc-type registry assert (1.1), banned-copy scan (4.2).
- Playwright compliance E2E: intake → attestation → simulate (qwen3.5-fast) → doc gen → blocked export until citations verified.

---

**Rule of thumb @coderbot:** if a control appears here, it is a *server-side or DB-side* constraint, never a UI-only affordance. Every row marked S1–S3 must exist before the feature that depends on it ships to the next stage.

**Prod-port note:** every control in §1–§5 except 2.2 (TLS) is verifiable entirely on localhost with the Ollama provider. Phase 2 adds only: Bedrock Sydney pinning + invocation logging (2.1, 3.2, 3.3), MFA at clinic tier (2.3), and the breach/data-flow docs (2.5, 2.6).