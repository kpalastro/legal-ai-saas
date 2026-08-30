# LexSim AI — Tech Stack (v2.1, August 2026)

> **v2.1 — Local-First MVP decision (user directive):** v1 runs **entirely on localhost** with all LLM inference served from the local **Ollama** daemon (`http://localhost:11434`). Bedrock Sydney remains the production target (Phase 2) behind an `LLM_PROVIDER` env switch — the inference layer is abstracted so provider swap is one config change, zero code change.

**Status:** Supersedes the stack in `ARCHITECTURE.md`. Incorporates every critical/high finding from `REVIEW.md` (AustLII prohibition, DeepSeek-V3 hosting impossibility, SC Gen 23 restrictions, auth/RLS breakage, over-engineering) and upgrades all components to current stable releases (verified Aug 2026).

**Design principles:** API-first inference (no self-hosted GPU), no AustLII anywhere, Supabase Auth (fixes the `auth.uid()` RLS mismatch), monolith-first, SSE over WebSocket for MVP, open-source-first (Apache/MIT licensed components).

---

## Stack at a Glance

| Layer | Technology | Version (verified Aug 2026) | License | Why |
|---|---|---|---|---|
| Frontend | Next.js (App Router) | **16.3.3** (Active LTS, includes Aug 2026 critical security patch) | MIT | Latest stable; `npm install next@16.3.3` |
| UI language | React | 19.x | MIT | Pairs with Next.js 16 |
| Type system | TypeScript | 5.9.x | Apache-2.0 | |
| Styling | Tailwind CSS | v4.x | MIT | New engine, faster builds |
| Component kit | shadcn/ui + Radix primitives | current | MIT | Copy-in components, full a11y control (WCAG 2.1 AA) |
| Data fetching | TanStack Query | v5 | MIT | |
| State | Zustand | v5 | MIT | |
| Forms/validation | React Hook Form + Zod | v4 / v4 | MIT | Zod schemas shared FE↔BE via generated client |
| Streaming | **SSE** (not WebSocket) | — | — | Debates are server→client only; simpler, works on serverless |
| API client | `@hey-api/openapi-ts` | current | MIT | Auto-generated from FastAPI OpenAPI schema — FE/BE never drift |
| Backend | FastAPI | 0.11x | MIT | Async-first, native SSE, OpenAPI for free |
| Python | **3.13** | 3.13.x | PSF | Latest stable; MCP/Pydantic fully supported |
| ORM | SQLAlchemy 2.0 async + asyncpg | 2.0.x | MIT | `Mapped[]` typed models |
| Migrations | Alembic | 1.14+ | MIT | |
| Pkg manager | **uv** | 0.8+ | Apache-2.0 | 10–100× faster pip, lockfile-native |
| Config | pydantic-settings | v2 | MIT | 12-factor env config |
| Database | PostgreSQL 17 (Supabase) | 17.x | PostgreSQL | RLS, JSONB |
| Auth | **Supabase Auth** | current | Apache-2.0 | Fixes `auth.uid()` RLS mismatch; email/password + Google OAuth native; Clerk deferred to enterprise tier (Phase 3, with `request.jwt.claims.sub` claims mapping) |
| Row-level security | Supabase RLS | — | — | `user_id = auth.uid()` now actually works |
| Cache / rate limit / queue | Redis 7 (Upstash serverless in prod) | 7.x | RSAL/Redis source-available; Upstash managed | |
| Background jobs | **arq** (NOT Celery) | 0.26+ | MIT | Redis-based asyncio jobs — simulations, doc gen, citation checks |
| File storage | Supabase Storage → S3 (ap-southeast-2) at scale | — | — | Webhook to re-derive presigned URLs |
| PDF/DOCX parsing | pymupdf, python-docx | current | AGPL-3.0 / MIT | Intake document extraction |
| Doc templates | Jinja2 | 3.1.x | BSD | Statement of claim, defence, chronology |
| LLM inference (v1 local) | **Ollama** (OpenAI-compatible `/v1` API on localhost:11434) | latest | MIT | Zero cost, zero data egress — data never leaves the machine during dev |
| v1 debate agent (local) | **qwen3.5:latest** (6.6 GB) — 3 in-context agent personas | — | Apache-2.0 | Best available local reasoning model on this machine; tool-capable; fits 16–24 GB |
| v1 fallback (local, low-RAM) | `qwen3.5-fast:latest` (1.0 GB) / `qwen3.5:0.8b` (1.0 GB) | — | Apache-2.0 | Smoke tests + CI without loading the big model |
| Inference abstraction | `llm/` adapter interface: `OllamaProvider` ↔ `BedrockProvider` (boto3) | — | — | `LLM_PROVIDER=ollama|bedrock`; identical OpenAI-style chat API both sides |
| Quality tier | DeepSeek V3.2 (Bedrock) | — | MIT (open-weights) | ~A$0.21/case |
| Premium/lawyer tier | Claude Sonnet 5 (Bedrock) | — | commercial | ~A$2.28/case |
| Dev self-host option (Phase 4 only) | vLLM serving gpt-oss-120b (MXFP4 fits a single 80GB GPU — the only open 100B+ model that does) | vLLM 0.10+ | Apache-2.0 | Only if volume >10k cases/mo; will not be needed |
| Citation sources (v1 local) | Federal Register of Legislation OData API (free) + NSW Caselaw (fetch/cached HTML); JADE deferred to Phase 2 | — | — | **AustLII is banned** for any AI/programmatic use — not an API, actively Cloudflare-blocked, policy covers manual access too |
| Payments | Stripe (AUD, GST invoicing) — **v1: Stripe test mode only, run locally** | — | commercial | — |
| Auth (v1 local) | **Supabase Auth self-hosted via Docker** (or dev-only JWT bypass flag) | — | Apache-2.0 | Keeps `auth.uid()` RLS semantics identical to production |
| Email (v1 local) | MailHog / Mailpit SMTP catch-all in Docker | — | MIT | SendGrid only wired in Phase 2 |
| E2E testing | Playwright | current | Apache-2.0 | Full suite runs on localhost against Ollama |
| CI (v1 local-first) | GitHub Actions + **local pytest/vitest/Playwright** | — | — | CI smoke tests use `qwen3.5:0.8b` so no big-model load needed |
| Containers | Docker Compose (dev) | — | — | postgres:17-alpine, redis:7-alpine, uvicorn --reload |
| Hosting | Vercel (FE) + Fly.io/Railway (API+arq worker) for MVP → EKS/RDS/ElastiCache Sydney at scale | — | — | |
| Observability | Sentry + OpenTelemetry → Grafana Cloud free tier | — | — | |
| E2E testing | Playwright | current | Apache-2.0 | |
| Monorepo | pnpm workspaces + Turborepo | pnpm 9/10, Turbo 2.x | MIT | FE + BE + generated api-client in one repo |

---

## Localhost v1 — Dev Environment (canonical)

Everything runs on this machine. No cloud dependency for the full feature loop.

```yaml
# infra/docker-compose.yml  (v1 local)
services:
  postgres:
    image: postgres:17-alpine        # port 5432 — cases, simulations, RLS policies
  redis:
    image: redis:7-alpine            # port 6379 — arq queue, cache, rate limits
  supabase-auth:
    image: supabase/gotrue:latest    # port 9999 — JWT issuer; RLS uses auth.uid()
  mailpit:
    image: axllent/mailpit           # port 8025 — catches all SMTP locally
  api:
    build: ../apps/api
    command: uvicorn app.main:app --reload --port 8000
    environment:
      LLM_PROVIDER: ollama
      OLLAMA_BASE_URL: http://host.docker.internal:11434   # host Ollama daemon
      LLM_MODEL: qwen3.5:latest
      DATABASE_URL: postgresql://lexsim:dev@postgres:5432/lexsim
  worker:
    build: ../apps/api
    command: arq app.worker.WorkerSettings
    environment: { LLM_PROVIDER: ollama, OLLAMA_BASE_URL: http://host.docker.internal:11434 }
  web:
    build: ../apps/web               # Next.js 16.3.3, port 3000
```

**Ollama serves the 3 debate agents** (USER_ADVOCATE / OPPONENT / JUDGE) as three in-context personas over the same `qwen3.5:latest` model via its OpenAI-compatible endpoint — no multi-model orchestration needed for v1. Model swaps (e.g. larger `qwen3.5:397b-cloud` for the JUDGE role to test quality deltas) are a per-agent config string.

```bash
# .env (v1 local) — verified working values
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=qwen3.5:latest          # CAD for tests: qwen3.5:0.8b
# Phase 2 swap — zero code change:
# LLM_PROVIDER=bedrock
# BEDROCK_REGION=ap-southeast-2
# BEDROCK_MODEL=openai.gpt-oss-120b-1:0
```

**Local test strategy (all localhost):** pytest unit tests (debate state machine, citation parser, doc gate) → arq integration tests with `qwen3.5-fast:latest` → Playwright E2E of the full intake→debate→document flow with `qwen3.5:latest` → hallucination-score assertions on the citation verifier. Nothing leaves the machine.

### Ollama Runtime Pitfalls (verified live on this machine, 30 Aug 2026; §6 amended after live scaffold round-trip) — @coderbot bake into `OllamaProvider` day 1

> **⚠️ CORRECTION (post-scaffold, verified live by @coderbot + re-verified in repo):** for the qwen3.5 family on this machine, **the `/v1` OpenAI-compat layer is the broken layer** — thinking goes to a separate `reasoning` field while `content` returns empty, and `max_tokens` counts the hidden reasoning tokens, so per-turn budgets are consumed invisibly and every turn returns `""` with `finish_reason: length`. `think:false` and `chat_template_kwargs.think:false` are both **ignored over `/v1`** (verified — reasoning still generated). `OllamaProvider` therefore targets **`/api/chat`** :82-95 in `apps/api/app/llm/ollama.py`, where `think:false` works server-side, `options` are honored, and `prompt_eval_count`/`eval_count` come back. All pins below still apply — they're just applied over the endpoint that actually respects them.

1. **No model is loaded right now** (`/api/ps` returns `[]` — daemon is up but idle). Every first call after idle pays the 6.6 GB load. Two options, pick one in `OllamaProvider`: call `POST /api/generate` with `"keep_alive": -1` once at app startup (pins the model in VRAM), or an arq startup job that warms it. Otherwise turn-1 of the debate times out and the SSE stream shows a blank first frame.
2. **262k tokens of context ≠ usable KV cache.** Verified `hw.memsize` = **32 GB** unified memory on this Mac; `qwen3.5:latest` advertises `context_length 262144`, but allocating KV cache for even ~64k tokens of stacked legal transcripts + intake docs on top of the 6.6 GB weights will swap and hang the whole debate. Cap it: `num_ctx: 32768` is the safe ceiling (32 GB headroom: 6.6 GB weights + ≤4 GB KV at 32k + OS + Docker + Chrome); set `num_predict: 2048` per turn. Pass these in the `options` dict of the request body, **not** the `Parameters` block of the Modelfile (Modelfile params silently break when the compat layer re-serializes). On `/api/chat` use `num_predict` directly; on `/v1`, `max_tokens` is the equivalent field — but note it counts hidden reasoning tokens for the qwen3.5 family (see correction above), which is another reason `/v1` is off the table.
3. **Default sampler params are wrong for court personas and adversarial coherence.** Verified via `/api/show`: shipped defaults are `temperature 1`, `top_k 20`, `presence_penalty 1.5`. `top_k 20` will kill it in a 1–2 GB vocab. For v1 agents set in the request `options`: `temperature 0.15` (JUDGE) / `0.3` (or lawyers), `top_p 0.9`, `top_k 40`, `repeat_penalty 1.1`. Keep `presence_penalty`/`frequency_penalty` unset — don't port OpenRouter defaults over.
4. **Non-deterministic verdict JSON** — the JUDGE turn must emit `{lower, point, upper}` schema. `temperature 0` via `/v1` is still sampled (Mirostat off but sampling path ignores `temperature=0` unless `seed` is also passed); pin a fixed `seed` in the JUDGE request so CI determinism tests (@testing's stubbed vs live tiers) have reproducible verdict structure. Also strip `<think>…</think>` traces from output before parsing — the qwen3.5 family emits reasoning traces fast by default.
5. **Connection base:** the API container must use `OLLAMA_BASE_URL=http://host.docker.internal:11434` (already in compose above) — `localhost` inside the container points at the container itself, and the silent failure mode is a 60s connect timeout mid-debate, not a clean startup error. Add a `/health/llm` endpoint that pings `GET {OLLAMA_BASE_URL}/api/tags` at startup and fails fast if down.

---

## Repository Layout

```
legal-ai-saas/
├── apps/
│   ├── web/                     # Next.js 16.3.3 (App Router, RSC, SSE client)
│   │   ├── app/(auth)/login
│   │   ├── app/dashboard
│   │   ├── app/case/new           # plain-language intake wizard
│   │   ├── app/case/[id]/simulate # live debate viewer (SSE)
│   │   └── app/case/[id]/docs     # doc generator + citation confirmation
│   └── api/                     # FastAPI single-process monolith
│       ├── app/
│       │   ├── agents/            # debate state machine + 3 agent roles
│       │   ├── citations/         # FRL API + NSW Caselaw + JADE verifiers
│       │   ├── documents/         # Jinja2 templates (NO affidavit/expert report)
│       │   └── ...
│       └── worker/              # arq worker (same image as api)
├── packages/
│   └── api-client/              # @hey-api/openapi-ts — autogenerated, never hand-edited
├── infra/
│   ├── docker-compose.yml       # postgres:17, redis:7, api, worker, web
│   └── terraform/               # (Phase 2+) RDS/ElastiCache ap-southeast-2
└── .github/workflows/ci.yml    # lint + typecheck + pytest + vitest + playwright
```

## What Changed vs. ARCHITECTURE.md

| Was | Now | Reason |
|---|---|---|
| Next.js 14 | **Next.js 16.3.3** | Latest Active LTS; includes the Aug 2026 critical security patch |
| Clerk.dev + broken `auth.uid()` RLS | **Supabase Auth** | `auth.uid()` works natively; one vendor fewer at MVP |
| SGLang / vLLM self-hosted DeepSeek-V3 on 1×A100 | **Bedrock Sydney gpt-oss-120b API** | DeepSeek-V3 (671B MoE) needs ~8×H200 ≈ A$41k/mo (58× the budgeted $715); API COGS is ~A$0.06/case |
| AustLII citation verification + BGE-M3 RAG | **FRL API + NSW Caselaw + JADE** | AustLII prohibits all AI/programmatic use, incl. manual-access-then-process |
| Celery + Redis | **arq** | Async-native, one dependency pile lighter |
| WebSocket + Kong API Gateway | **SSE** via FastAPI streaming + Vercel/Fly direct | Debates unidirectional; cuts two services |
| Kong / AWS API Gateway | Dropped for MVP | Over-engineering for 10-user beta |
| Affidavit & expert report generation | **Removed** | SC Gen 23 para 10/20 prohibit — hard-blocked in code and UI |
| AI-only citation verification | AI-assisted + **mandatory human confirmation gate** | SC Gen 23 para 17 (two AU lawyers already sanctioned for hallucinated citations) |

## Compliance Guards Baked Into the Stack (not bolt-on)

1. `documents/` generator registry contains no affidavit/witness-statement/expert-report template; selection UI hides them for AU jurisdictions.
2. Every generated doc carries an auto "AI Assistance Disclosure" footer.
3. Citation export is blocked until every citation row is `✅ Verified` AND `user_reviewed = true` (DB CHECK constraint, not just UI).
4. Outcome prediction renders as a calibrated range with "not legal advice" copy, never a bare point estimate (ACL s18/s29 risk).
5. All inference pinned to ap-southeast-2 endpoints; no cross-border model routing (APP 8).

## Compliance Additions (v2.1, 30 Aug 2026) — required in scaffold

Carried from `REQUIREMENTS.md` §Compliance + @compliance's review; @testing maps these to gate IDs:

| # | Control | Implementation point |
|---|---|---|
| C1 | **Append-only `audit_log`** table — every AI input/output stored; UPDATE/DELETE rejected at DB (trigger + revoke), not app-side | New Alembic migration; schema: `id, case_id, user_id, event_type, model_id, prompt_ref, response_ref, created_at`. Supports LPP disputes and G5. |
| C2 | **Bedrock model invocation logging** enabled in ap-southeast-2 (CloudWatch/S3 Sydney sinks ONLY — APP 8); prompt/response storage `DISABLED` (Restricted where supported) | AWS config asserted by a CI config test (no-training/no-retention flags; Sydney-region sink ARNs) |
| C3 | **7-year case retention job** — arq scheduled job auto-archives then erases cases past 7y (app-level cascade erasure incl. Storage objects + audit_log retention per policy) | arq cron worker in `worker/`; calendar note: legal-hold override flag on `cases` |
| C4 | **OAIC breach-notification workflow stub** — incident template + notifier job (30-day assessment window) | `compliance/` module; wired to Sentry alerting |
| C5 | **Export gate = 3 conditions** — all citations `✅ Verified` AND `user_reviewed = true` AND `simulations.user_attestation = true`; enforce as DB CHECK + API guard + UI disable (G2 tests each independently) | Extends guard #3 above |
| C6 | **Schema regression guard** — CI test asserting no migration ever reintroduces `clerk_user_id` | @testing's permanent guard; scaffold must ship the Supabase Auth DDL from day 1 |