# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

LexSim AI: a multi-agent legal debate simulator for Australian self-represented litigants. Three personas (USER_ADVOCATE / OPPONENT / JUDGE) argue a case over a fixed 9-turn protocol against one local LLM, streamed over SSE, producing a calibrated outcome range plus citation-verified document generation and deadline calculation.

The product is deliberately conservative for NSW SC Gen 23 / APP 8 / legal professional privilege. Compliance controls are enforced in code and in Postgres, not in comments — treat gates G1–G8 (below) as invariants, not suggestions.

## Commands

Prerequisites: Docker, Ollama, `uv` (Python 3.13+), Node 22 / npm.

### Infrastructure

```bash
ollama pull qwen3.5:0.8b                   # ~1 GB local smoke tier
ollama pull qwen3.5:latest                 # optional ~6.6 GB quality tier
cd infra && docker compose up -d           # postgres :5434, redis :6379, GoTrue :9999, mailpit :8025
```

The compose file also builds/starts `api` (:8000) and `worker`. To run the API on the host instead, start only dependencies:

```bash
cd infra && docker compose up -d postgres redis supabase-auth mailpit
```

Note: dev Postgres is published on **:5434** (not :5432 — that port belongs to another local stack). `app/config.py`, `tests/conftest.py` and `apps/api/.env.example` all use :5434.

Every app transaction runs `SET LOCAL ROLE lexsim_app` (configurable via `DB_APP_ROLE`) because the dev DSN is the `postgres` superuser, and superusers bypass RLS even with FORCE. `DB_REQUIRE_NON_SUPERUSER=true` fails closed if the effective role can bypass RLS.

### API

```bash
cd apps/api
uv sync --group dev
uv run python scripts/run_migrations.py              # migrations + lexsim_app grants
uv run uvicorn app.main:app --port 8000 --reload --log-config log_config.json
```

`alembic upgrade head` applies migrations but not the app-role grants; use the
script for a fresh dev DB. CI applies the grants explicitly after migrations.

`--log-config log_config.json` wires `TokenScrubFilter`, which redacts `?token=` JWTs from uvicorn logs. Keep it.

### Tests and checks (run from `apps/api`)

```bash
uv run pytest -q                                     # 94 passed (4 CORS skip without a live API)
uv run pytest -m compliance                          # SC Gen 23 / RLS / audit / deny-list gates
uv run pytest tests/test_features.py::test_g3_prohibited_doc_types_rejected -q
uv run ruff check .                                  # CI gate
uv run mypy app                                      # CI gate
uv run pytest --cov=app --cov-report=json:coverage.json --cov-fail-under=80
uv run python scripts/check_money_path_coverage.py  # per-file compliance-path floor
uv run python scripts/evaluate_examples.py          # worked-example structural check
```

Tests share one event loop (`asyncio_default_*_loop_scope = "session"` in
`pyproject.toml`) because the app's module-global asyncpg pool cannot hand a
connection bound to a previous test loop to the next test.

### Web

```bash
cd apps/web && npm ci && npm run dev                 # Next.js 16.3.3 on :3000
cd apps/web && npx tsc --noEmit && npm run build     # CI web job
```

The web app is one client component (`app/page.tsx`) with the full workspace:
auth, intake, uploads, live debate, attestation, document review/export,
deadlines and plans. API/GoTrue URLs come from `NEXT_PUBLIC_API_URL` and
`NEXT_PUBLIC_GOTRUE_URL` (defaults are localhost). Root `pnpm dev/build/test`
point at Turbo, but there is no `turbo.json`; run the web app directly.

### Container drift

```bash
bash infra/scripts/drift_check.sh                    # fails if infra-api-1 lacks the working-tree code
```

Stale-container bugs have bitten this repo twice; rebuild with `docker compose -f infra/docker-compose.yml up -d --build api` after API edits.

## Architecture

```
apps/api   FastAPI monolith + arq worker      (Python 3.13, SQLAlchemy async/asyncpg, Alembic)
apps/web   Next.js 16.3.3 / React 19 demo     (:3000)
infra      docker-compose + postgres-init stub + drift/auth-stub scripts
requirement/  design + compliance records; docs/ holds current architecture diagrams
```

### Request path

`apps/web` → GoTrue login → `GET /cases/{id}/simulate` with `Authorization: Bearer <jwt>` → FastAPI `get_db()` → Postgres with RLS → Ollama → SSE frames.

- `app/db.py::get_db` is **fail-closed**: no verified HS256 JWT means no DB session at all. It delegates to `arm_request()`, which (transaction-locally) runs `SET LOCAL ROLE <DB_APP_ROLE>`, pins `search_path = public, auth`, sets `request.jwt.claims` from the verified payload, and fails closed if the effective role is superuser/BYPASSRLS. Claims come only from the verified payload, never client input.
- GoTrue v2.196 issues `aud: ""`; decoding intentionally skips audience verification (`verify_aud: False`) while still checking signature/exp/sub. Do not "fix" this to `audience="authenticated"`.
- SSE uses fetch + ReadableStream with the Authorization header (see `apps/web/app/page.tsx`). The legacy `?token=` query fallback has been removed; `tests/test_sse_auth_surface.py` pins header-only auth. Do not add query-token clients.

### Debate engine

`app/agents/debate_state_machine.py` is the authority: a linear cursor over `PROTOCOL` (exactly 9 turns, JUDGE belief updates at 3/6/9). It is deliberately not a graph, so out-of-order or skipped turns are impossible by construction.

`app/agents/engine.py::run_debate` drives the cursor. It is **case-grounded and stateful**: `case_context()` reads facts, parties, issues, relief and court/file number, then retrieves the most relevant uploaded chunks (`app/documents/retrieval.py`, Postgres full-text) instead of dumping every exhibit. Every prompt carries the transcript so far plus any user interventions. Per turn it writes one `audit_log` + `audit_content` pair with real prompt/response hashes, `prompt_version` and the model digest, and **commits immediately**. The SSE router claims the case (`status='simulating'`), streams each `on_turn` payload, persists the verdict + `simulation_id`, and resets the case on failure/cancel. Tests assert structure (turn order, audit rows, verdict schema), never LLM prose.

`verdict_from_text()` validates the JUDGE JSON: integers, `0 <= lower <= point <= upper <= 100`. Anything else degrades to `{raw: ...}` so the UI still shows a compliant range guard. Every verdict carries `methodology_note` ("not a statistical prediction").

### Case intake, uploads and documents

- `cases` stores `description`, `parties`, `issues`, `relief_sought`, `court`, `case_number` (migration 0003); `GET/PATCH /cases/{id}` expose them.
- `POST /cases/{id}/documents` accepts PDF/DOCX/TXT/MD/CSV up to 20 MB, sniffs magic bytes, strips the filename to a basename, stores under `STORAGE_DIR` with 0600 perms, hashes it, and extracts text (PyMuPDF / python-docx). The raw file is never served by the API.
- `POST /documents/generate` links the draft to a simulation (explicit `simulation_id` or the latest for the case) and returns the citation provenance + gate status. `POST /simulations/{id}/attest` records `user_attestation`/`user_attested_at`; `POST /documents/{id}/attest` records `user_reviewed`.
- `GET /documents/{id}/export?format=txt|docx|pdf` re-checks citations, review, simulation link and attestation, then emits a real file. The DB trigger also requires a non-NULL `simulation_id` when `exported=true` (0003 closed the NULL-link bypass).
- Citation verification is concurrent (bounded to 50 refs, 5 at a time), records `checked_at` and an evidence snippet, and never returns VERIFIED without source concurrence.

### Analysis, retrieval and upload chunks

- `POST /simulations/{id}/analysis` is a **post-debate analysis, not a tenth protocol turn** (G6 stays fixed at nine). It asks the provider for a structured weakness report, validates/bounds the JSON (`parse_weakness_report`), computes a citation-risk score from verified/unverified/flagged citations, stores `weakness_report` + `hallucination_score`, and audits the analysis request.
- Uploads are chunked (`app/documents/chunking.py`) into `document_chunks`; retrieval ORs the case's meaningful terms (`to_tsquery`) so a query built from several issues does not AND itself into zero matches. If ranking finds nothing, it falls back to the earliest chunks.

### Plans, legal hold and privacy

- `app/entitlements.py` maps `subscription_tier` → case/simulation limits and enforces them at the API edge with 402. The Stripe webhook is the only writer of the tier.
- `POST /cases/{id}/legal-hold` blocks erasure and the retention sweep.
- `GET /users/me/export` returns portable matter data (cases, simulations, uploads metadata, generated docs, deadlines, audit metadata).
- `POST /users/me/erase` (confirm `"ERASE"`) de-identifies case content, deletes chunks/raw uploads and tombstones the profile, while **retaining append-only audit rows** for LPP/legal obligations. `app/privacy.py` is the shared implementation used by the endpoint and `retention_sweep`. The GoTrue identity must be removed separately.

### Organisations, RBAC and sharing

- `organisations` + `memberships` (owner/admin/lawyer/paralegal/viewer); `cases.org_id` shares a matter with the org. RLS grants org members SELECT and writer roles INSERT/UPDATE/DELETE.
- Membership checks use `SECURITY DEFINER` helpers (`is_org_member`, `is_org_writer`, `is_org_admin`, `is_org_owner`, `case_visible`, `case_writable`) because a policy on `memberships` that queries `memberships` would recurse.
- Write endpoints call `require_case_writer()` for a clean 403 instead of an RLS WITH CHECK exception. Only the case creator can share/unshare; the owner role is immutable and cannot be removed.
- `consents` records the APP 5 collection-notice acknowledgement (`POST /users/me/consent`).

### Document versions, signatures, conflicts and resources

- `generated_documents` carry `version`, `version_group_id`, `supersedes_id`, `superseded` and `content_sha256`. `POST /documents/{id}/revise` creates the next version and marks the old one superseded; superseded rows cannot be attested, signed or exported. `GET /documents/{id}/versions` lists the chain.
- `POST /documents/{id}/sign` requires `user_reviewed=true`, records a typed-name signature bound to the content hash, and is one-per-version. Export adds version/hash/signer headers.
- `conflicts` is a per-organisation conflict register; `GET /conflicts/check?name=` searches visible matter parties plus the register. Matches are leads for a human, not a clearance.
- `app/resources.py` + `GET /legal/resources` expose AU crisis/legal-aid referrals. The UI shows them for family/criminal/violence-type matters; verify the numbers before publication.
- `POST /users/me/erase` calls the optional GoTrue admin delete when `GOTRUE_ADMIN_URL` + `GOTRUE_SERVICE_ROLE_KEY` are set; otherwise it reports `identity_deleted=false`.

### Legal registry and metrics

- `app/legal_registry.py` is a deliberately conservative pointer: cause-of-action element checklists and court AI-policy entries (SC Gen 23, Federal Court GPN-AI, FCFCOA, generic verify). It is not legal advice; every response carries the disclaimer. `case_context()` appends the elements checklist, and the analysis prompt asks for `claims` and `elements`.
- `app/metrics.py` exposes in-process Prometheus counters at `/metrics` (HTTP requests, LLM calls/tokens, uptime). There is no external sink yet; multi-instance prod should scrape or use OpenTelemetry.

### Billing and operations

- `app/billing.py` creates real Stripe Checkout Sessions (503 if `STRIPE_SECRET_KEY` is absent) and verifies `Stripe-Signature` HMACs before granting `subscription_tier`. `POST /billing/webhook` is signature-authenticated, not JWT-authenticated.
- `RequestContextMiddleware` adds `X-Request-ID`, caps bodies, sets security headers and logs method/path/status/duration. `app/ratelimit.py` is Redis-backed with an in-memory fallback; it guards simulate/upload/generate/citations/billing.
- `/health/db` reports both the privileged connection role and the effective app role, and whether RLS is actually enforced.

### LLM provider layer

`app/llm/` is the only place `LLM_PROVIDER` is read. `OllamaProvider` (v1) and `BedrockProvider` (Phase 2) share `LLMProvider.complete()` and must emit the same audit shape (`audit_event_shape`; parity test).

Ollama quirks are load-bearing:
- Use `/api/chat`, not `/v1`. On `/v1`, qwen3.5 thinking lands in a hidden `reasoning` field, `content` returns empty, and `max_tokens` is consumed invisibly.
- Send `think:false`, `num_ctx=32768`, `num_predict=2048`, `keep_alive=-1`, and the role sampler presets from `app/llm/presets.py`.
- The JUDGE role alone gets `seed=42` for reproducible verdict structure.
- Bedrock config fails startup unless region is `ap-southeast-2` and the model ID is regional (no `global./apac./us./eu.` prefixes).

### Compliance gates

| Gate | Control | Where |
|---|---|---|
| G1 | RLS tenant isolation on all 7 tables | `alembic/versions/0001`, `0002` (FORCE RLS) |
| G2 | Export blocked unless citations verified + user reviewed + simulation linked AND attested | DB triggers + `routers/features.py` 403/409 |
| G3 | Affidavit / witness statement / expert report / evidentiary material hard-blocked | `documents/registry.py`, DB CHECK, UI |
| G4 | AI-assistance disclosure footer always appended | `documents/generator.py` |
| G5 | Audit append-only; every AI input/output persisted verbatim | `audit.py`, DB triggers |
| G6 | Exactly 9 debate turns, fixed order | `agents/debate_state_machine.py` |
| G7 | AustLII is deny-listed; never fetch it | `citations/service.py` |
| G8 | No cross-region Bedrock model IDs | `config.py` + CI grep |

The export gate has three independent layers (API check, DB trigger, RLS). A bypass at the API layer still hits the DB trigger. Do not weaken any one layer on the assumption another covers it.

Citations are verified deterministically against the Federal Register of Legislation and NSW Caselaw. An unreachable source degrades to `unverified`, never `verified`. AustLII must not appear in any outbound URL, including in extracted citation strings.

### Data model

Tenant tables: `cases`, `documents`, `simulations`, `generated_documents`, `deadlines`, `audit_log`, `audit_content`, plus `document_chunks` (retrieval, RLS through its case), `organisations`, `memberships`, `consents`, `signatures` and `conflicts`. Child tables join visibility through `cases`; `audit_content` holds verbatim prompts/responses and is backend-only (no tenant read policy). `public.users` references `auth.users(id)`; there is no `clerk_user_id` anywhere and a regression test enforces that. Migrations 0003–0006 add intake/document/attestation columns, indexes, retrieval chunks, provenance, privacy fields, organisations/RBAC, consents, document versions/signatures and the conflict register.

Dev supplies an `auth` schema stub (`infra/postgres-init/01-auth-stub.sql`) with `auth.uid()` and `auth.role()` handling plural and singular claim GUCs. Never deploy the stub; production uses hosted Supabase Auth.

### Worker

`worker/main.py` provides `run_simulation` (same debate engine as the SSE path, on an `AsyncSession` so per-turn commits work) and a nightly `retention_sweep` (7 years, honors `legal_hold`). `persist_result()` returns the new simulation id, moves the case to `completed`, and is imported by the SSE router so the two paths stay transactionally identical. On failure the worker resets the case to `intake`; already-committed audit rows remain.

## Non-obvious invariants

- **Migrations must be `.py`.** Alembic only executes `versions/*.py`; a parallel `.sql` file is documentation, not execution. `0002_force_rls.sql` exists only because the `.py` version is now authoritative.
- **Multi-statement `op.execute` blocks are split** by patched `do_execute` handlers in `alembic/env.py` and `scripts/run_migrations.py`, because asyncpg rejects multi-command prepared statements. Keep SQL splittable or extend the splitters.
- **SQL comments in these paths use `--`, never `#`.** `#` caused a psql syntax failure in CI.
- **CI order matters:** auth stub/role first → `alembic upgrade head` → DML grants (`install_auth_stub.py --grants-only`) → pytest. Grants cannot precede table/sequence creation.
- **RLS binds at runtime, not just in tests.** `arm_request()` runs `SET LOCAL ROLE lexsim_app` on every request transaction; the dev DSN is the `postgres` superuser, and superusers bypass RLS even with FORCE. Tests must do the same role switch or they prove nothing. `/health/db` must report `rls_enforced: true`.
- **Schema resolution is pinned to `public`.** Migrations start with `SET LOCAL search_path = public, auth` and qualify `public.<table>`. The dev GoTrue init once put `auth` first on the *role* search_path, so unqualified `CREATE TABLE` landed in `auth` while CI landed in `public` — a real dev/CI divergence. Never re-add a role-level search_path; scope it to the `gotrue` database.
- **Audit durability is per turn.** `run_debate` commits after each `write_audit_row`; do not move that commit to the end of the run or a disconnect will erase the C1/G5 trail. Transaction-local role/claims are re-armed by `arm_request()` before each turn.
- **Export needs a linked, attested simulation.** `generated_documents.simulation_id` must be non-NULL; migration 0003's trigger enforces it and the API returns a clean 403. `POST /documents/{id}/attest` only sets `user_reviewed`; simulation attestation is separate.
- **Uploads never enter the web root or the repo.** `STORAGE_DIR` (default `./storage`) holds raw files with 0600 perms; only extracted text/chunks are persisted in Postgres. Keep `storage/` gitignored.
- **Erasure must not delete audit rows.** `public.cases` cascades into `audit_log`, whose DELETE trigger is intentional; use `app/privacy.py` tombstones (content overwritten, audit retained) rather than `DELETE FROM cases`. Set `generated_documents.exported=false` before clearing a simulation attestation or the export trigger will raise.
- **The analysis endpoint is not a debate turn.** G6 fixes the protocol at nine; weakness analysis is a separate audited request. Do not add a tenth `Turn`.
- **Retrieval uses OR-ed terms.** `plainto_tsquery` ANDs everything, so a multi-issue query silently matched nothing and fell back to the first chunks. `to_tsquery` with `|` is deliberate; keep the fallback.
- **Plan limits are enforced at the edge.** `create_case` and `simulate_sse` call `enforce_*_limit` and return 402; do not rely on the UI to hide actions.
- **Org policies must not recurse.** Any membership check inside a policy goes through the `SECURITY DEFINER` helpers. A direct `EXISTS (SELECT ... FROM memberships ...)` in a `memberships` policy will recurse under RLS.
- **`cases_org_write` is `FOR ALL` and writer-only.** Viewers get SELECT via `cases_org_select`; write endpoints still pre-check with `require_case_writer()` so the API returns 403, not a DB error.
- **The legal registry is a pointer, not authority.** Elements/court policies carry verify notes; do not present them as settled law. Update by adding data after checking the current practice note.
- **The dev login role is not a production credential.** `lexsim_api:lexsim_api_dev` exists only in the dev init stub; prod uses a managed least-privilege role. `arm_request` still binds `lexsim_app` every request.
- **Superseded versions are frozen.** Do not attest, sign or export a row with `superseded=true`; revise first. The API returns 409 and export headers carry version/hash/signer evidence.
- **A signature is not a legal execution.** It records a typed name bound to the content hash; counsel must decide whether it satisfies the relevant court/esignature rules.
- **Conflict matches are not clearance.** The register/search only surfaces name matches; a human resolves conflicts. Do not change the response to imply “no conflict”.
- **Referral resources need verification.** Phone numbers/URLs in `app/resources.py` are a safety surface and can change; check before publication.
- **Sentry is optional and off by default.** `SENTRY_DSN` unset = no external error egress; `send_default_pii=False` is deliberate.
- **Tests share one event loop** (`asyncio_default_fixture_loop_scope` / `asyncio_default_test_loop_scope = "session"`). The app's module-global asyncpg pool otherwise hands a connection bound to a dead loop to the next test.
- **Test data must not leak into demos.** Use `[TEST]` names and purge fixtures before and after (TEST_PLAN §9; `test_audit_append_only.py` is the reference). Do not assert SQL errors where the doctrine requires asserting visibility-and-effect; always include the fail-closed zero-row case.
- **Never assert on LLM prose.** Only structure: turn order, verdict schema `{lower, point, upper}`, citation status enums, footer presence, DB row shapes.
- **Compliance tests are non-skippable on protected paths** (`documents/`, export, RLS, audit). If you touch those, run `uv run pytest -m compliance`.
- **`apps/web` is Next.js 16.3.3 with breaking changes from older Next versions.** `apps/web/AGENTS.md` (imported by `apps/web/CLAUDE.md`) requires reading `node_modules/next/dist/docs/` before writing web code. Do not assume App Router conventions from training data.
- **Provider swap is config-only:** `LLM_PROVIDER=bedrock` + pinned region/model must work without touching the debate engine. Keep changes behind `LLMProvider`.

## Documentation map

Canonical: `docs/ARCHITECTURE.md` (current topology), `requirement/TECH_STACK.md` (stack + Ollama pitfalls), `requirement/TEST_PLAN.md` (gate matrix, §8 RLS doctrine, §9 fixture hygiene), `requirement/COMPLIANCE_CHECKLIST.md`, `requirement/SECURITY_CHECKLIST.md`, `requirement/PENDING.md` (remaining work), `SECURITY.md` (security model/limitations), `docs/DEPLOYMENT.md`, `docs/DATA_FLOWS.md`, `docs/BREACH_RESPONSE.md`, and the draft `docs/PRIVACY_POLICY.md`/`docs/TERMS_OF_USE.md` (legal review required).

Stale / superseded: `requirement/REQUIREMENTS.md` (SQL/stack blocks superseded by TECH_STACK), `requirement/ARCHITECTURE.md` (deprecated banner). Trust the docs above instead.
