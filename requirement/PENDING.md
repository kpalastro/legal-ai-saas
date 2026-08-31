# Pending — single source of truth for remaining work

## Demo blockers: NONE

## Compliance acceptance (GRC, 31 Aug — feature-complete round)
Verified hands-on before acceptance: suite 57/57 (23 on `compliance` marker), 10 OpenAPI
paths serving, G3 banned doc types 422 at the API layer (`Affidavit` → 422 SC Gen 23,
case-insensitive), `DISCLOSURE_FOOTER` appended server-side and not omittable by template,
XSS payload in `case_title` auto-escaped out of the rendered document. Accepted.

## Phase 2 (pre-production, security chair owns)
- [ ] FORCE ROW LEVEL SECURITY on all six tenant tables OR app-role-only connection (postgres is owner+superuser → bypasses RLS by default)
- [ ] JWT secret rotation runbook (dev secret `dev-on...e-me` in .env.example)
- [ ] Replace SSE `?token=` with header-safe path: EventSource → fetch ReadableStream, or one-time stream-ticket exchange (get_db() docstring sketch); log scrub (3c38dbe) is the interim guard
- [ ] Log-retention hygiene: dev host logs still hold pre-scrub rotations; prod statement = access logs metadata-only, bounded retention (OAIC guidance: logs detect incidents, never store credentials)
- [ ] Real Stripe SDK + webhook signature verification (test-mode intent shipped a4c3a9a)
- [ ] G7 audit-file TODO: lexsim_app REVOKE scope check
- [ ] Bedrock account-level AI-services opt-out policy asserted in ap-southeast-2 before any real case data (no per-request no-training flag on Converse — see COMPLIANCE_NOTE in app/llm/bedrock.py)

## Phase 2 (infra)
- [ ] CI `drift` job needs a macOS self-hosted runner registered (job is wired in ci.yml, runs-on: [self-hosted, macOS]; script proven locally: infra/scripts/drift_check.sh)
- [ ] Bedrock Sydney provider swap test (LLM_PROVIDER=bedrock, gpt-oss-120b) once AWS creds available

## Cosmetic / tracked elsewhere
- [x] Turn-9 UI copy polish (a12d314)
- [x] .next/ untracked from git (1d33440)
- [x] Test fixtures excluded from runtime image (69b2f3c)
