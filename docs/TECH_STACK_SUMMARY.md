# LexSim AI — Tech Stack Presentation

> Presentation summary of the stack decisions for LexSim AI, the multi-agent
> legal debate simulation platform. Companion to `TECH_STACK.md` (canonical
> detail) and `README.md` (developer quick start).

---

## Slide 1 — The product

**LexSim AI** simulates Australian courtroom proceedings before you walk in.

- USER_ADVOCATE, OPPONENT and JUDGE argue your case over **9 structured turns**
  (openings → belief updates → rebuttals → closings → verdict).
- You get an outcome **prediction range** (calibrated, never a bare number),
  a weakness report, and court-ready documents with **verified citations**.
- Built for self-represented litigants and solo practitioners who can't afford
  $300–800/hr counsel — but need to know where their case stands.

## Slide 2 — Why localhost-first?

| Decision | Driver |
|---|---|
| **Ollama on this Mac** (qwen3.5:latest) | Legal data never leaves the machine — the strongest LPP/APP-8 posture for a dev stack; zero inference cost at beta scale |
| **Docker Compose** (postgres:17, redis:7, GoTrue, Mailpit) | One-command reproducible environment; identical RLS semantics to hosted Supabase in production |
| **Stripe test-mode** | Billing flows behave without touching real money |
| One env switch (`LLM_PROVIDER=ollama\|bedrock`) | Production swap to Bedrock Sydney is config-only, zero code |

## Slide 3 — The inference model (and the traps we dodged)

| Candidate | Verdict |
|---|---|
| Self-hosted DeepSeek-V3 on 1×A100 | ❌ Needs ~8×H200 (~A$41k/mo). Dead on arrival |
| Bedrock Sydney gpt-oss-120b | ✅ **Production target** — Apache 2.0 open-weights, ~A$0.06/case, AU data residency |
| **Ollama + qwen3.5 (v1)** | ✅ **Shipped today** — same `openai.gpt-oss-120b` family of reasoning; zero cost; zero egress |

**Live-hardened lessons** (now tested invariants, not comments): the `/v1`
OpenAI-compat layer drops qwen3.5 thinking into a hidden `reasoning` field and
burns `max_tokens` on it → we ship `/api/chat` with `think:false`; every
request carries `num_ctx:32768` (the 32 GB Mac ceiling) + `num_predict:2048`;
JUDGE pins `seed=42` for reproducible verdicts; warm-up pins the model resident
so turn-1 never blanks.

## Slide 4 — Verification stack (the part lawyers actually care about)

1. **Deterministic citation parser** — extracts medium-neutral citations
   (`[2024] NSWSC 1101`) and Act references.
2. **Two allowed sources** — Federal Register of Legislation API + NSW Caselaw.
   **AustLII is deny-listed in code** — the module raises before any HTTP call.
3. **Three-layer export gate** — API 403 + DB triggers + RLS visibility, all
   enforcing: every citation `verified` + user reviewed + user attested (SC Gen
   23 para 17; two AU lawyers already sanctioned for hallucinated citations).
4. **Offline-honest fallback** — an unreachable source yields UNVERIFIED, never
   fabricated VERIFIED (pinned by test).

## Slide 5 — Data residency & privilege

- Postgres 17 with **RLS on all six tenant tables**; the app connects via a
  `NOBYPASSRLS` role so isolation is enforced by Postgres, not by app code.
- Fail-closed auth: a request without a verified GoTrue JWT gets *no database
  session at all*.
- Append-only `audit_log` + `audit_content` (verbatim prompt/response, LPP
  reconstructable, UPDATE/DELETE rejected by trigger — only a DB superuser can
  touch it, and the app role structurally can't).
- All AI inference local in v1; Phase 2 Bedrock is ap-southeast-2 pinned by a
  startup-fail test.

## Slide 6 — Numbers

| | |
|---|---|
| MVP features | 6/6 complete |
| Tests | 57 (all 7 gates: RLS, export, footer, banned types, audit, deny-list, debate order) |
| API surface | 10 OpenAPI paths |
| Inference cost @ 100 users (v1, local) | **A$0** |
| Inference cost @ 100 users (Phase 2, Bedrock) | ~A$6/mo |
| Monthly infra (Vercel + Fly + Supabase + Upstash) | ~$105/mo |

## Slide 7 — What's deliberately not done yet

Phase 2, tracked in `requirement/PENDING.md`: FORCE RLS + secret rotation before
real case data, header-safe SSE (drop `?token=`), real Stripe SDK + webhook
verification, Bedrock Sydney swap, self-hosted CI runner for the drift job.