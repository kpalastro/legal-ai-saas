# Pending — single source of truth for remaining work

## Demo blockers: NONE

The full localhost loop is working: auth → intake → upload/extract → live
9-turn grounded debate → simulation attestation → document generation →
citation gate → DOCX/PDF export → deadlines/limitations → plans.
Suite: 94 passed (4 CORS tests run only when the API is live), coverage ~82%.

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

## Completed 2026-11-19 (phase 2 — trust, tenancy and privacy)

- **Retrieval over uploads.** `document_chunks` + Postgres full-text search;
  the debate gets the relevant passages, not the first N characters.
- **Weakness analysis.** `POST /simulations/{id}/analysis` returns a bounded,
  validated structured report (issue/severity/evidence gap/next step) plus a
  citation-risk score; stored on `simulations.weakness_report` and audited.
- **Prompt/model provenance.** `audit_log.prompt_version` + `model_digest`;
  Ollama's immutable digest is captured at warm-up.
- **Plan entitlements.** Tier → case/simulation limits enforced at the API edge
  (402); `/users/me` and `/billing/plans` expose limits/usage.
- **Legal hold, DSAR and erasure.** `POST /cases/{id}/legal-hold`;
  `GET /users/me/export`; `POST /users/me/erase` de-identifies content and
  removes uploads while retaining append-only audit rows.
- **Retention execution.** `retention_sweep` de-identifies cases past 7 years
  (unless held) instead of only archiving.
- **Calendar + reminders.** `.ics` deadline export; daily arq reminder job via
  Mailpit/SMTP, marked `reminder_sent`.
- **Web workspace.** Weakness analysis, quotas, legal hold, data export,
  account de-identification, calendar download.
- **Tests.** 88 passed, ~82% coverage; retrieval/analysis/quota/privacy/retention
  covered. Tracked editor junk removed.

## Completed 2026-11-19 (phase 3 — tenancy, legal registry, hardening)

- **Organisations/RBAC.** `organisations` + `memberships`
  (owner/admin/lawyer/paralegal/viewer), `cases.org_id` sharing, RLS for org
  visibility/writes via `SECURITY DEFINER` helpers, org/member API and UI.
  Owner role is immutable; only the case creator can share/unshare.
- **Legal registry.** Cause-of-action element checklists and court AI-policy
  pointers (SC Gen 23, Federal Court GPN-AI, FCFCOA, generic verify), wired into
  the debate context and analysis prompt.
- **Claim/element analysis.** The post-debate report now also returns claim
  support and an element checklist, bounded/validated in `parse_weakness_report`.
- **Consent records.** `consents` table + `POST /users/me/consent`; the web sign-in
  records the APP 5 acknowledgement.
- **Header-only SSE.** The `?token=` fallback and OpenAPI parameter are removed;
  the test pins their absence.
- **Least-privilege DB login.** Dev compose uses a `lexsim_api` login role that
  binds `lexsim_app`; `/health/db` reports `connection_privileged=false` and
  `rls_enforced=true`.
- **Metrics.** In-process Prometheus counters at `/metrics` (HTTP/LLM/tokens).
- **Ops/docs.** `SECURITY.md`, draft privacy/terms, data-flow register, breach
  runbook, deployment checklist, prod compose overrides, backup script,
  Dependabot, money-path coverage gate, example evaluator, load/backfill scripts.
- **Tests.** 92 passed, ~82% coverage; money-path per-file floors pass.

## Completed 2026-11-19 (phase 4 — document lifecycle and safety)

- **Document versioning.** `version`, `version_group_id`, `supersedes_id`,
  `superseded`, `content_sha256`; `POST /documents/{id}/revise` creates the next
  version and freezes the old one; `GET /documents/{id}/versions` lists the chain.
- **Typed-name signatures.** `signatures` table + `POST /documents/{id}/sign`
  (requires review, binds the content hash; one per version). Export headers
  carry version/hash/signer evidence.
- **More safe templates.** `schedule_of_damages` and `list_of_documents` added to
  the SC Gen 23 allow-list; banned types remain blocked.
- **Conflict register.** Party-name search across visible matters plus a
  per-organisation register; writer-only inserts; human resolution required.
- **Support resources.** AU crisis/legal-aid referral endpoint and a UI banner
  for family/criminal/violence matters.
- **GoTrue identity deletion.** Optional admin-API delete during erasure;
  `identity_deleted` is reported, with a console fallback note.
- **Sentry (optional).** `SENTRY_DSN` enables error reporting with PII disabled;
  unset = no egress.
- **Ops.** Restore script, report-only dependency/secret scan script, prod
  overrides, and updated security/privacy/deployment docs.
- **Tests.** 94 passed, ~82% coverage.

## Completed 2026-11-19 (phase 5 — review and lifecycle)

- **Document review comments.** `document_comments` with RLS through the
  document's case; add/resolve/reopen/delete; writer-only writes.
- **Version diff.** `GET /documents/{id}/diff` (or `?against=`) returns a
  unified diff within the same version group; UI "Compare".
- **Settlement/cost analysis.** The analysis now returns an indicative range,
  factors and cost/procedural risks, with the preparation-assistance disclaimer.
- **Subscription lifecycle.** Checkout writes subscription metadata, supports
  automatic tax/tax IDs and optional trials; `customer.subscription.deleted`
  downgrades to free.
- **Accessibility/polish.** Skip link, focus-visible rings, reduced-motion CSS,
  ARIA status/current attributes; HTML+text reminder emails.
- **Tests.** 94 passed, ~82% coverage; comments/diff/settlement/cancellation and
  the 0007 migration are covered.

## Remaining — trust and legal accuracy

- [ ] **RAG over authoritative sources.** Retrieval now works over the user's
  own uploads, but not over legislation/case law. AustLII is correctly banned; a
  top-tier product needs licensed sources or structured official APIs, with
  pinpoint citations and source snippets attached to claims.
- [ ] **Good-law and point-in-time checks.** Existence is not enough: overruled/
  distinguished authorities, repealed/amended legislation and "as at" dates.
- [ ] **Citation coverage.** Parallel/authorised-report citations, pinpoint
  paragraphs, delegated legislation, tribunal decisions, court-specific styles.
- [ ] **Calibration/backtesting.** The verdict is a model-generated scenario
  range with a methodology note. A production product needs base rates,
  backtests against decided matters, and expert review; consider framing as
  scenario analysis rather than probability.
- [ ] **Claim-level grounding.** The citation-risk score is aggregate; individual
  factual/legal assertions are not tied to a source. Consider a claim-extraction
  + verification pass.
- [ ] **Evaluation harness.** Gold cases, expert grading, regression tests for
  legal quality, red-team/prompt-injection tests. The structural example script
  is in place; legal-quality grading still needs expert review.
- [ ] **Court policy data review.** The registry exists, but each entry
  (especially GPN-AI/FCFCOA and the generic fallback) must be checked against the
  current published version before launch.
- [ ] **Analysis-quality review.** The weakness/claim/element analysis is
  model-generated; validate its taxonomy against lawyer-reviewed fixtures.

## Remaining — professional platform

- [ ] SSO/SAML/SCIM for enterprise tiers (orgs/RBAC and sharing are done).
- [ ] Client portal, visual redlining, court forms, e-filing integrations.
  (Versioning, unified diff, comments and typed-name signatures are done; a
  signature is not legal execution and must be reviewed by counsel.)
- [ ] Court forms, DOCX/PDF formatting per court, versioning/diff/redline,
  e-signature, e-filing integrations.
- [ ] Evidence-sufficiency and ADR/negotiation workflow beyond the model-generated
  settlement range/cost risks (element checklists are done).
- [ ] Full WCAG audit, plain-language rewrite, translations and mobile-first
  flows. (Skip link, focus rings, reduced-motion and ARIA status/current are in.)
- [ ] Integrations: DMS, accounting, court portals (calendar export + email
  reminders are done).

## Remaining — privacy, security, compliance

- [ ] **GoTrue identity deletion in production.** The app calls the admin API
  when `GOTRUE_ADMIN_URL`/`GOTRUE_SERVICE_ROLE_KEY` are configured; set them and
  verify in prod. Otherwise `identity_deleted=false` and the console is required.
- [ ] **SSO/MFA/refresh hardening.** Hosted Supabase Auth configuration, MFA
  enrolment, refresh rotation, and httpOnly/BFF token storage.
- [ ] **Audit-content retention policy.** Append-only audit rows are retained
  (LPP/legal obligations); decide the `audit_content` window and document the
  tension with APP 11/13 in the privacy policy.
- [ ] Privacy policy, terms, collection notice, consent records, DPA,
  cross-border data-flow register, breach workflow (stub in
  `app/compliance/breach.py`).
- [ ] MFA/password policy, refresh-token rotation/revocation, httpOnly/BFF
  token storage (the browser currently stores tokens in `localStorage`).
- [x] Dedicated least-privilege DB login role (`lexsim_api` in dev compose;
  confirm/rotate the managed role in prod). `?token=` removal is done.
- [ ] Vulnerable-user escalation workflow (referral resources and conflict
  checks are done), lawyer escalation, practising-certificate verification.
- [ ] SOC 2/ISO 27001 readiness, pen test, vulnerability disclosure, backups/DR,
  IaC (Terraform), container/dependency scanning.
- [ ] Observability: configure `SENTRY_DSN` (implemented, PII off) or
  OpenTelemetry; build SLOs/dashboards. `/metrics` is in-process only.
- [ ] Real Stripe keys + live webhook test; tax invoice/GST entity setup and
  dunning (automatic tax, optional trials, cancellation downgrade and
  entitlements/quotas are implemented).

## Remaining — engineering hygiene

- [x] Money-path per-file coverage floors (`scripts/check_money_path_coverage.py`)
  are enforced in CI; raise the thresholds as tests land.
- [ ] Frontend component tests and Playwright E2E (the web CI job only
  type-checks and builds).
- [ ] Load/performance tests: `scripts/load_sse.py` exists but is not wired into
  CI or run against a staging stack.
- [x] Migration backfill helper (`scripts/backfill_document_simulations.py`) for
  legacy documents with NULL `simulation_id`.
- [x] Restore script and report-only dependency/secret scan
  (`infra/scripts/restore_postgres.sh`, `infra/scripts/security_scan.sh`);
  schedule a restore drill and make the scan blocking after triage.
