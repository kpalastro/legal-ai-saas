# Pending — single source of truth for remaining work

## Demo blockers: NONE

The full localhost loop is working: auth → intake → upload/extract → live
9-turn grounded debate → simulation attestation → document generation →
citation gate → DOCX/PDF export → deadlines/limitations → plans.
Suite: 77 passed (4 CORS tests skip when the API is not running), coverage ~82%.

## Completed 2026-11-19 (product-loop completion round)

- **Runtime RLS actually binds.** `arm_request()` runs `SET LOCAL ROLE lexsim_app`
  on every request transaction and fails closed if the effective role is
  superuser/BYPASSRLS. `/health/db` reports the effective role.
- **Schema resolution fixed.** GoTrue's role-level `search_path = auth, public`
  had made every app table land in `auth` in dev while CI created them in
  `public`. Removed the role-level setting; migrations pin
  `SET LOCAL search_path = public, auth` and qualify `public.<table>`.
- **Case-grounded, stateful debate.** `case_context()` now includes facts,
  parties, issues, relief, court/file number and extracted upload text; each
  turn carries the transcript so far and user interventions.
- **Audit durability.** One audit pair per turn with real prompt/response hashes;
  commits after every turn, so a disconnect/failure cannot erase turns 1..N-1.
- **Case intake + uploads.** `cases.description/parties/issues/relief/court/
  case_number`; PDF/DOCX/TXT/MD/CSV upload with magic-byte validation, 20 MB cap,
  0600 storage outside the web root, SHA-256 and extracted text.
- **Simulation lifecycle.** Case claimed as `simulating`, moved to `completed`,
  reset to `intake` on failure/cancel; simulation history/detail endpoints;
  explicit SC Gen 23 simulation attestation with timestamp.
- **Export path is reachable and gated.** Drafts link to a simulation;
  `POST /documents/{id}/attest` records review; `GET /documents/{id}/export`
  emits TXT/DOCX/PDF. Migration 0003 closes the NULL-`simulation_id` trigger
  bypass.
- **Indexes + `updated_at` trigger** on the tenant tables.
- **Deadlines/limitations.** Persisted deadlines; Easter computed; state
  holidays; limitation periods for NSW contract/tort/personal injury.
- **Citations.** Concurrent (bounded), provenance (`checked_at`, evidence
  snippet), still offline-honest (unverified, never invented VERIFIED).
- **Billing.** Real Stripe Checkout Session creation + HMAC webhook verification;
  503 rather than a fake URL when unconfigured.
- **Operations.** Request ids, body-size cap, security headers, Redis/in-memory
  rate limits, `/health/db`, deterministic tests (stubbed LLM, session loop).
- **Web workspace.** Intake, uploads, live debate, attestation, document
  review/export, deadlines/limitations, plans, refresh-token handling, logout,
  privacy/LPP acknowledgement.
- **CI.** Web job (npm ci / tsc / build), migration downgrade+upgrade guard,
  coverage gate; grants script now applies app-role grants for dev.

## Remaining — trust and legal accuracy

- [ ] **Retrieval/RAG over authoritative sources.** The model is grounded in the
  user's own materials but not in legislation/case law. AustLII is correctly
  banned; a top-tier product needs licensed sources or structured official APIs,
  with pinpoint citations and source snippets attached to claims.
- [ ] **Good-law and point-in-time checks.** Existence is not enough: overruled/
  distinguished authorities, repealed/amended legislation and "as at" dates.
- [ ] **Citation coverage.** Parallel/authorised-report citations, pinpoint
  paragraphs, delegated legislation, tribunal decisions, court-specific styles.
- [ ] **Calibration/backtesting.** The verdict is a model-generated scenario
  range with a methodology note. A production product needs base rates,
  backtests against decided matters, and expert review; consider framing as
  scenario analysis rather than probability.
- [ ] **Claim-level grounding / hallucination score.** The column exists but is
  never computed; prose assertions are not checked against sources.
- [ ] **Weakness report.** `simulations.weakness_report` is still unwritten; it
  needs a post-debate analysis pass or a structured evidence/issues matrix.
- [ ] **Model/prompt version pinning.** `qwen3.5:latest` is mutable; audit rows
  record only the model name. Record digests and prompt versions.
- [ ] **Evaluation harness.** Gold cases, expert grading, regression tests for
  legal quality, red-team/prompt-injection tests.
- [ ] **Court-by-court AI policy registry.** SC Gen 23 is NSW Supreme Court-
  specific; other courts/tribunals have their own expectations.

## Remaining — professional platform

- [ ] Organisations/teams, RBAC, SSO/SAML/SCIM for lawyer/clinic tiers.
  (`users.role` and `subscription_tier` exist but do not gate anything yet.)
- [ ] Client/matter sharing, comments, collaborative review.
- [ ] Court forms, DOCX/PDF formatting per court, versioning/diff/redline,
  e-signature, e-filing integrations.
- [ ] Deadline reminders (email/calendar) and e-filing calendars.
- [ ] Weakness/strategy views: elements checklist, evidence sufficiency,
  settlement/ADR analysis, costs/risk.
- [ ] Accessibility (WCAG), plain language, translations, mobile-first flows.
- [ ] Integrations: calendar, email, DMS, accounting, court portals.

## Remaining — privacy, security, compliance

- [ ] **DSAR/erasure design.** `audit_log.case_id ON DELETE CASCADE` plus the
  append-only DELETE trigger means account/case erasure cannot complete as
  designed. Need tombstone/de-identification + legal-hold design.
- [ ] Retention execution: `retention_sweep` currently archives only
  (`erased: 0`); audit content retention window still undecided.
- [ ] Privacy policy, terms, collection notice, consent records, DPA,
  cross-border data-flow register, breach workflow (stub in
  `app/compliance/breach.py`).
- [ ] MFA/password policy, refresh-token rotation/revocation, httpOnly/BFF
  token storage (the browser currently stores tokens in `localStorage`).
- [ ] Dedicated least-privilege production DB login role (dev uses `postgres` +
  `SET ROLE`); remove `?token=` after its one-release window.
- [ ] Vulnerable-user safeguards, lawyer escalation, conflict checks,
  practising-certificate verification.
- [ ] SOC 2/ISO 27001 readiness, pen test, vulnerability disclosure, backups/DR,
  IaC (Terraform), container/dependency scanning.
- [ ] Observability: Sentry/OpenTelemetry, metrics/SLOs/dashboards (request ids
  and access logs are in place, but there is no external sink).
- [ ] Real Stripe keys + live webhook test; entitlements/quota enforcement,
  GST invoices, trials, dunning.

## Remaining — engineering hygiene

- [ ] 100% coverage on money paths (`debate_state_machine`, citations,
  `documents/registry`, export-gate path) is asserted in TEST_PLAN but not
  enforced separately.
- [ ] Frontend component tests and Playwright E2E (the web CI job only
  type-checks and builds).
- [ ] Remove tracked editor swap files / `tsconfig.tsbuildinfo`
  (`git rm --cached` still to be committed).
- [ ] Load/performance tests for the SSE path and citation fan-out.
- [ ] Migration data backfills (if any prod data exists) before enabling the
  0003 export trigger.
