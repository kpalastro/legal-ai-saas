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

**MVP feature-complete and running on localhost** — see [PENDING.md](requirement/PENDING.md)
for the (non-blocking) remainder. 57 tests green, all 7 CI gates live: RLS
tenant isolation, export gate, banned-doc-type hard block, disclosure footer,
audit trail, citation-source deny-list, and debate protocol order.

## What it does (MVP v1.0)

| # | Feature | Where |
|---|---------|-------|
| 1 | Auth + multi-tenancy — GoTrue (Supabase-compatible) JWTs, Postgres RLS, fail-closed token verification | `apps/api/app/routers/cases.py`, `app/db.py` |
| 2 | Case intake + document upload | `app/routers/cases.py` |
| 3 | **9-turn multi-agent debate** — USER_ADVOCATE / OPPONENT / JUDGE personas over one local LLM, streamed live over SSE, calibrated-range verdict `{lower, point, upper}` + "not legal advice" | `app/agents/engine.py`, `GET /cases/{id}/simulate` |
| 4 | **Document generator + citation verification** — 5 SC Gen 23-allowed types, FRL/NSW-Caselaw lookup, AustLII hard-denied, three-layer export gate | `app/citations/`, `app/documents/`, `app/routers/features.py` |
| 5 | **Deadline calculator** — AU court business days + public holidays, per-jurisdiction rules | `app/deadlines/` |
| 6 | Billing — Stripe test-mode checkout intents ($49/$149/$99/$299 plans) | `POST /billing/checkout` |

## Architecture (one page)

```
┌────────────────────────────────────────────────────────────────────┐
│  apps/web — Next.js 16.3.3 (React 19, Tailwind v4)  → :3000        │
│    login · case list · intake · live SSE debate viewer · verdict   │
└──────────────┬─────────────────────────────────────────────────────┘
               │ fetch (JWT header) + EventSource (?token=, v1 only)
               ▼
┌────────────────────────────────────────────────────────────────────┐
│  apps/api — FastAPI monolith + arq worker            → :8000       │
│   agents/  9-turn state machine (G6: linear cursor, no skips)      │
│   citations/  FRL + NSW Caselaw lookup, AustLII deny-list (G7)     │
│   documents/  Jinja2 gen, G3 hard block, C5 export gate            │
│   deadlines/  AU business-day rules per court                      │
│   llm/  provider abstraction: Ollama (v1) ↔ Bedrock (Phase 2)      │
│   db.py  fail-closed JWT → RLS claims; audit writer (C1)           │
└──────┬──────────────────────┬─────────────────────┬────────────────┘
       ▼                      ▼                     ▼
┌─────────────┐   ┌────────────────────┐   ┌──────────────────────┐
│ postgres:17 │   │ redis:7 (arq queue)│   │ Ollama :11434 (host) │
│ RLS on all  │   │                    │   │ qwen3.5:latest       │
│ tenant tbls │   │                    │   │ 3 personas, 1 model  │
└─────────────┘   └────────────────────┘   └──────────────────────┘
  + GoTrue :9999 (JWT)  · Mailpit :8025 (dev email)
```

Every AI call is audited (`audit_log` + full-text `audit_content`, both
append-only at the DB) so any output can be reconstructed for an LPP dispute.

## Quick start

```bash
# prerequisites: Docker, Ollama, pnpm, python 3.13
ollama pull qwen3.5:latest          # ~6.6 GB
cd infra && docker compose up -d    # postgres, redis, gotrue, mailpit
cd ../apps/api && ./scripts/run_migrations.py
uvicorn app.main:app --port 8000 &  # API (or docker compose up api)
cd ../web && pnpm install && pnpm dev  # :3000
cd ../apps/api && pytest -q         # 57 tests, all 7 compliance gates
pytest -m compliance                # can't be skipped on protected paths
```

Full environment values: [infra/docker-compose.yml](infra/docker-compose.yml),
[apps/api/.env.example](apps/api/.env.example).

## Compliance posture (why it looks conservative)

- **SC Gen 23 (NSW Supreme Court)**: affidavits/witness statements/expert
  reports are hard-blocked at the registry, API (422), and DB CHECK. Citation
  export requires human verification + attestation (para 17).
- **DoNotPay precedent**: no outcome guarantees; every verdict is a calibrated
  range with "not legal advice" copy; deadlines are labelled preparation
  assistance.
- **APP 8 / LPP**: v1 inference never leaves this machine (Ollama); the audit
  trail stores verbatim prompts/responses for reconstruction; Phase 2 moves to
  Bedrock Sydney with account-level opt-out policy asserted before real data.

## Documentation

| Doc | Purpose |
|-----|---------|
| [requirement/REQUIREMENTS.md](requirement/REQUIREMENTS.md) | product requirements (⚠️ SQL/stack blocks superseded — see TECH_STACK) |
| [requirement/TECH_STACK.md](requirement/TECH_STACK.md) | canonical stack + Ollama runtime pitfalls |
| [requirement/TEST_PLAN.md](requirement/TEST_PLAN.md) | test matrix, §8 RLS doctrine, §9 fixture hygiene |
| [requirement/COMPLIANCE_CHECKLIST.md](requirement/COMPLIANCE_CHECKLIST.md) | 24 controls → clauses → proof |
| [requirement/SECURITY_CHECKLIST.md](requirement/SECURITY_CHECKLIST.md) | S1–S4 controls incl. localhost/Ollama |
| [requirement/SECURITY_AUDIT_20260830.md](requirement/SECURITY_AUDIT_20260830.md) | feature-complete round audit |
| [requirement/PENDING.md](requirement/PENDING.md) | tracked remaining work |
| [requirement/examples/](requirement/examples/) | 4 worked example cases (family, property, criminal, negligence) |

## Team process

- Suite: `pytest -q` (57) — `pytest -m compliance` is forced-on for PRs touching
  `documents/`, `export`, `rls`, `audit`.
- Drift check: `bash infra/scripts/drift_check.sh` — fails if the running api
  container's code diverges from the working tree (this bug class bit twice).
- Isolation-test doctrine (TEST_PLAN §8): never assert SQL errors — assert
  visibility-and-effect; always include the fail-closed zero-row case.