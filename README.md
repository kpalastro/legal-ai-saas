# LexSim AI — Multi-Agent Legal Debate Simulation

Multi-agent legal debate simulation platform for Australian self-represented
litigants (SRLs) and solo practitioners. Simulates courtroom adversarial
proceedings to predict case outcomes, identify weaknesses, and generate
court-ready documents with verified citations.

> **This tool does not replace legal advice.** It provides simulation and
> preparation assistance only. You remain responsible for all court filings.
> Every generated document carries an AI-assistance disclosure, and exports are
> blocked until every citation is verified against an authoritative source AND
> you attest your review (NSW Supreme Court Practice Note SC Gen 23).

## Current status

**Working end-to-end on localhost** — auth, case intake, document upload and
text extraction, retrieval-backed 9-turn debate, weakness/claim/element analysis
with a citation-risk score, simulation attestation, document generation,
DOCX/PDF/TXT export, deadlines/limitation periods, calendar export, plan quotas,
organisations/RBAC and matter sharing, legal registry (elements + court AI
policies), document versioning, typed-name signatures, review comments, version
diff, settlement/cost analysis, conflict checks, support/referral resources,
legal hold, data export/de-identification, metrics, and Stripe checkout/webhooks
with subscription cancellation (test-mode when keys are configured).

94 backend tests green (4 CORS tests run only when the API is live), plus 3
Vitest unit tests and 2 Playwright browser smoke tests, including the seven
compliance gates: RLS tenant isolation, export gate, banned-doc-type hard block,
disclosure footer, audit trail, citation-source deny-list, and debate protocol
order. Remaining Phase-2 work is tracked in
[requirement/PENDING.md](requirement/PENDING.md).

## What it does

| # | Feature | Where |
|---|---------|-------|
| 1 | Auth + multi-tenancy — GoTrue JWTs, Postgres RLS, fail-closed token verification, least-privilege app role | `apps/api/app/db.py`, `app/routers/cases.py` |
| 2 | Case intake + document upload — facts, parties, issues, relief, court/file number; PDF/DOCX/TXT/MD/CSV extraction | `app/routers/features.py`, `app/documents/storage.py` |
| 3 | **Retrieval-backed 9-turn debate** — intake facts, Postgres full-text retrieval over uploaded chunks, transcript memory, optional interventions, streamed over SSE, validated calibrated-range verdict | `app/agents/engine.py`, `app/documents/retrieval.py` |
| 4 | **Document generator + citation verification** — 5 SC Gen 23-allowed types, FRL/NSW-Caselaw lookup with provenance, AustLII hard-denied, three-layer export gate, DOCX/PDF export | `app/citations/`, `app/documents/`, `app/routers/features.py` |
| 5 | **Weakness analysis** — post-debate structured analysis (issue, severity, evidence gap, next step) + citation-risk score derived from verified/unverified/flagged citations | `POST /simulations/{id}/analysis` |
| 6 | **Deadline + limitation calculator** — AU court business days, computed Easter/state holidays, persisted deadlines, NSW limitation periods, `.ics` export, email reminders | `app/deadlines/`, `worker/main.py` |
| 7 | **Plans and privacy** — per-tier case/simulation quotas, Stripe checkout/webhooks, legal hold, JSON data export, de-identification erasure, 7-year retention sweep, consent records | `app/entitlements.py`, `app/privacy.py`, `app/billing.py` |
| 8 | **Organisations/RBAC** — owner/admin/lawyer/paralegal/viewer memberships, matter sharing, RLS-enforced org visibility/write rules | `app/organisations.py`, migration 0005 |
| 9 | **Legal registry** — cause-of-action element checklists and court AI-policy pointers (SC Gen 23, GPN-AI, generic verify) | `app/legal_registry.py` |
| 10 | **Document versions + signatures** — version groups, supersession, content hashes, typed-name signature bound to the hash; export records version/hash/signer headers | migration 0006, `app/routers/features.py` |
| 11 | **Conflict checks + support resources** — party-name search across visible matters and the org register; AU crisis/legal-aid referral list | `app/routers/conflicts.py`, `app/resources.py` |
| 12 | **Review workflow** — document comments/resolve, unified version diff, settlement/cost analysis from the debate | `app/routers/comments.py`, `GET /documents/{id}/diff` |
| 13 | Operations — request ids, body-size cap, Redis rate limiting, `/health/db` RLS posture, `/metrics`, optional Sentry, per-turn audit durability, prompt/model provenance, subscription cancellation downgrade | `app/middleware.py`, `app/ratelimit.py`, `app/metrics.py`, `app/billing.py` |

## Architecture (one page)

```
┌────────────────────────────────────────────────────────────────────┐
│  apps/web — Next.js 16.3.3 (React 19, Tailwind v4)  → :3000        │
│    login · matters · intake · uploads · live SSE debate · docs     │
└──────────────┬─────────────────────────────────────────────────────┘
               │ fetch (JWT header) + fetch ReadableStream (SSE)
               ▼
┌────────────────────────────────────────────────────────────────────┐
│  apps/api — FastAPI monolith + arq worker            → :8000       │
│   agents/  9-turn state machine; case-grounded prompts             │
│   citations/  FRL + NSW Caselaw, provenance, AustLII deny-list     │
│   documents/  upload/extract, Jinja2, export gate, DOCX/PDF        │
│   deadlines/  AU business days, holidays, limitations              │
│   billing/    Stripe checkout + signed webhooks                    │
│   db.py  fail-closed JWT → SET LOCAL ROLE + claims → RLS           │
└──────┬──────────────────────┬─────────────────────┬────────────────┘
       ▼                      ▼                     ▼
┌─────────────┐   ┌────────────────────┐   ┌──────────────────────┐
│ postgres:17 │   │ redis:7 (arq + RL) │   │ Ollama :11434 (host) │
│ RLS + FORCE │   │                    │   │ qwen3.5 (local)      │
└─────────────┘   └────────────────────┘   └──────────────────────┘
  + GoTrue :9999 (JWT)  · Mailpit :8025 (dev email)
```

Every AI call is audited (`audit_log` + full-text `audit_content`, both
append-only at the DB). Each turn is committed individually, so a disconnect or
later failure cannot erase the audit trail for completed turns.

The export gate has three independent layers: API checks, DB triggers, and RLS.
A document cannot link to nothing: it carries a `simulation_id`, and export
requires the simulation's user attestation plus the document's review flag.

## Quick start

```bash
# prerequisites: Docker, Ollama, uv, python 3.13+, node 22+
ollama pull qwen3.5:0.8b            # local smoke tier (~1 GB)
ollama pull qwen3.5:latest          # optional full-quality tier (~6.6 GB)

cd infra && docker compose up -d    # postgres :5434, redis, gotrue, mailpit

cd ../apps/api
uv sync --group dev
uv run python scripts/run_migrations.py   # migrations + lexsim_app grants
uv run uvicorn app.main:app --port 8000 --reload --log-config log_config.json

cd ../web
npm ci && npm run dev               # :3000 (or npm run build && npm start)
```

Dev Postgres is published on **:5434**, not :5432 (another local stack owns
:5432). `apps/api/.env.example` has the verified values. Set
`LLM_MODEL=qwen3.5:0.8b` for fast local runs; the default in `.env.example` is
the smoke tier.

Compose also builds `api` and `worker`. If you run them in containers, rebuild
after API edits: `docker compose -f infra/docker-compose.yml up -d --build api`.

## Tests and checks

```bash
cd apps/api
uv run pytest -q                                     # 94 passed (4 skip without a live API)
uv run pytest -m compliance                          # SC Gen 23 / RLS / audit / deny-list
uv run pytest -q --cov=app --cov-fail-under=80       # CI gate
uv run ruff check . && uv run mypy app               # CI gates
cd ../web && npx tsc --noEmit && npm run build       # CI web job
cd ../web && npm test && npm run test:e2e            # Vitest + Playwright smoke
```

- **Tests never depend on a live LLM** — the engine uses stubbed providers in
  tests; live Ollama is a separate smoke tier.
- **RLS tests** switch to `lexsim_app`; the app does the same on every request
  (`SET LOCAL ROLE`), because the dev DSN is a superuser.
- **Drift check:** `bash infra/scripts/drift_check.sh` fails if the running api
  container's code diverges from the working tree.

## Compliance posture (why it looks conservative)

- **SC Gen 23 (NSW Supreme Court)**: affidavits/witness statements/expert
  reports are hard-blocked at the registry, API (422), and DB CHECK. Citation
  export requires human verification + attestation (para 17).
- **DoNotPay precedent**: no outcome guarantees; every verdict is a calibrated
  range with a methodology note and "not legal advice" copy. Deadlines and
  limitation periods are labelled preparation assistance.
- **APP 8 / LPP**: v1 inference stays on this machine (Ollama); the audit trail
  stores verbatim prompts/responses for reconstruction; Phase 2 moves to
  Bedrock Sydney with account-level opt-out asserted before real data.
- **Least privilege**: containers connect as the `lexsim_api` login role and
  every transaction binds `lexsim_app` (NOBYPASSRLS). `/health/db` reports the
  connection role, effective role and whether RLS is actually enforced.
- **Organisation isolation**: RLS extends case visibility to org members and
  restricts writes to writer roles; `SECURITY DEFINER` helpers avoid recursive
  membership policies.
- **Privacy**: legal hold blocks erasure/retention; `GET /users/me/export`
  returns portable matter data; erasure de-identifies case content and deletes
  uploads while retaining append-only audit records for LPP/legal obligations.
  The GoTrue identity is deleted separately via the auth admin API.

## Documentation

| Doc | Purpose |
|-----|---------|
| [requirement/TECH_STACK.md](requirement/TECH_STACK.md) | canonical stack + Ollama runtime pitfalls |
| [requirement/TEST_PLAN.md](requirement/TEST_PLAN.md) | test matrix, §8 RLS doctrine, §9 fixture hygiene |
| [requirement/COMPLIANCE_CHECKLIST.md](requirement/COMPLIANCE_CHECKLIST.md) | 24 controls → clauses → proof |
| [requirement/SECURITY_CHECKLIST.md](requirement/SECURITY_CHECKLIST.md) | S1–S4 controls incl. localhost/Ollama |
| [requirement/PENDING.md](requirement/PENDING.md) | tracked remaining work |
| [requirement/examples/](requirement/examples/) | 4 worked example cases |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | current topology (supersedes the requirement diagram) |
| [SECURITY.md](SECURITY.md) | security model, limitations, disclosure |
| [docs/PRIVACY_POLICY.md](docs/PRIVACY_POLICY.md) / [docs/TERMS_OF_USE.md](docs/TERMS_OF_USE.md) | draft policies (legal review required) |
| [docs/DATA_FLOWS.md](docs/DATA_FLOWS.md) / [docs/BREACH_RESPONSE.md](docs/BREACH_RESPONSE.md) | APP 8 register and OAIC runbook |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | production checklist and rollback |
