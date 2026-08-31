# Pending — single source of truth for remaining work

## Demo blockers: NONE

## Phase 2 (pre-production, security chair owns)
- [ ] FORCE ROW LEVEL SECURITY on all six tenant tables OR app-role-only connection (postgres is owner+superuser → bypasses RLS by default)
- [ ] JWT secret rotation runbook (dev secret `dev-on...e-me` in .env.example)
- [ ] Replace SSE `?token=` with header-safe path: EventSource → fetch ReadableStream, or one-time stream-ticket exchange (get_db() docstring sketch); log scrub (3c38dbe) is the interim guard
- [ ] Real Stripe SDK + webhook signature verification (test-mode intent shipped a4c3a9a)
- [ ] G7 audit-file TODO: lexsim_app REVOKE scope check

## Phase 2 (infra)
- [ ] CI `drift` job needs a macOS self-hosted runner registered (job is wired in ci.yml, runs-on: [self-hosted, macOS]; script proven locally: infra/scripts/drift_check.sh)
- [ ] Bedrock Sydney provider swap test (LLM_PROVIDER=bedrock, gpt-oss-120b) once AWS creds available

## Cosmetic / tracked elsewhere
- [x] Turn-9 UI copy polish (a12d314)
- [x] .next/ untracked from git (1d33440)
- [x] Test fixtures excluded from runtime image (69b2f3c)
