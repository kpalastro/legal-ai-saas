# LexSim AI — Security Checklist (v1, 30 Aug 2026)

**Owner:** @security · **Builds against:** `TECH_STACK.md` v2.1 + `TEST_PLAN.md` v1
**Covers:** the RLS sanity-check + Bedrock no-training/no-retention config @deploy and @compliance asked for, plus secrets/network hardening for the scaffold.
**Bedrock claims below were verified against AWS docs today (model-invocation-logging, API_Converse, geographic cross-region inference, PoLP security page).**

---

## S1. Bedrock — no-training / no-retention (answers @compliance's Converse question)

| # | Control | Verified fact (Aug 2026) | Implementation point |
|---|---------|--------------------------|----------------------|
| S1.1 | **No per-call "no-training flag" exists — don't scaffold for one.** Bedrock never trains base models on customer prompts/completions and never shares them with model providers, full stop. There is no request-level opt-in to set, so a `test_bedrock_config` assertion hunting for a "no_training" parameter on Converse will never pass — pin the region + model ID (S1.2) and the IAM scope (S1.4) instead. | AWS docs: "Amazon Bedrock never shares your data with model providers or uses it to train foundation models." | Intercepts TEST_PLAN `test_bedrock_config` — assert these controls instead of a nonexistent flag |
| S1.2 | **Region pinning is the real retention/residency control.** Call the regional model ID `openai.gpt-oss-120b-1:0` directly against `bedrock-runtime` in ap-southeast-2. Bedrock "doesn't store any text, images, or documents that you provide as content" on Converse (except transient safety/abuse screening, never shared with providers, never used for training). | Verified: API_Converse + abuse-detection docs | `apps/api/app/agents/` boto3 client config; **never** use `apac.*` or Global inference-profile IDs — see S1.3 |
| S1.3 | **Ban cross-region inference profiles (APP 8 trap).** A geography profile like `apac.anthropic.*` can route any `Converse`/`ConverseStream` call to other APAC regions, and where it routes, the input/output is stored in that destination region for abuse-detection. That is cross-border disclosure. Geo profiles keep data "within APAC" — that is **not** the same as within Australia, and not sufficient for APP 8. | Verified: geographic-cross-region-inference doc — "input prompts and output results might move outside of your source Region" and abuse-detection storage "will be stored in the destination region" | CI config test: scan all `modelId` literals in code/config — assert none match `^(global|apac|us|eu)\.`; IAM policy in S1.4 backstops it |
| S1.4 | **IAM hard-scoped, region-pinned bot.** One IAM role for the API/worker with only `bedrock:InvokeModel`/`InvokeModelWithResponseStream`/`Converse*` on the three model ARNs, with an explicit `aws:RequestedRegion == ap-southeast-2` deny-otherwise condition and an SCP denying `bedrock:Put*InferenceProfile`/global profile invocation. Wrong-region routing then fails closed rather than silently leaving Australia. | Standard PoLP | `infra/` Terraform policy doc; covered by residency allow-list test (TEST_PLAN P3) |
| S1.5 | **Model invocation logging — the honest spec.** `PutModelInvocationLoggingConfiguration` is region-scoped and **AWS only supports destinations in the same account + same region**, so a Sydney call with a Sydney log group/bucket inherently satisfies the Sydney-sink rule. Two decision points @compliance should sign off: (a) there is **no "Restricted" storage mode** in the logging config — REVIEW.md's language is not real; the switches are per-modality delivery booleans. (b) Tension between C1 and C2: LPP wants full AI inputs/outputs in our `audit_log` (app-side), while C2 wants Bedrock-side prompt/response storage off. Recommended split: **textDataDeliveryEnabled = false** → Bedrock logs carry metadata + token counts only (proves usage, keeps no second copy of privileged prompts); full prompt/response content lives solely in our append-only `audit_log` (C1, in our encrypted Postgres). If GRC later wants the AWS-side copy, flip text delivery on with a Sydney S3 bucket + KMS + 30-day lifecycle. | Verified: PutModelInvocationLoggingConfiguration / "Only destinations from the same account and Region are supported" | `infra/` IaC asserting `GetModelInvocationLoggingConfiguration` at deploy; CI test asserts the configured ARNs end in `ap-southeast-2` and `textDataDeliveryEnabled=false` |

## S2. RLS & multi-tenancy sanity-check

| # | Control | Implementation point |
|---|---------|----------------------|
| S2.1 | **Users table**: `id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE`, `email`, `role` — **no** `clerk_user_id`, no local user-management write path; Supabase Auth owns identity. | C6 / TEST_PLAN `test_schema_catches_regression` |
| S2.2 | **RLS on every tenant table, not just `cases`.** `cases`, `documents`, `simulations`, `generated_documents`, `deadlines`, `audit_log` each need `ENABLE ROW LEVEL SECURITY` + policy. `documents`/`simulations`/`generated_documents`/`deadlines` join through `case_id` — policy must be `EXISTS (SELECT 1 FROM cases WHERE cases.id = t.case_id AND cases.user_id = auth.uid())` (or FK-chain policy); a copy-paste `user_id = auth.uid()` policy on child tables silently matches zero columns (they have no `user_id`) and **fails closed** on inserts or gets dropped. Only `audit_log` differs: SELECT allowed for the owning user, INSERT by service role only, UPDATE/DELETE denied (G5/C1). | RLS DDL migration; G1 two-identity tests |
| S2.3 | **are database passwords never on the client.** FE uses only the anon key + Supabase Auth SDK; the API connects with the service role **only** in the API/worker containers, never exposed via API responses. Backend enforces RLS by forwarding the caller's Supabase JWT (set `request.jwt.claims`/`ALTER ROLE ... SET` or `set_config('request.jwt.claims', ...)` per connection in SQLAlchemy). | FastAPI dependency that verifies + injects the JWT per request |
| S2.4 | **Fail-safe default:** every new table created without an RLS policy must fail CI (test: query `pg_class`/`pg_policy` — any tenant table with `rowsecurity=false` or zero policies = red). | Alembic test in the schema-regression suite |

## S3. Secrets, PII, network

| # | Control | Implementation point |
|---|---------|----------------------|
| S3.1 | Secrets in env via pydantic-settings + Doppler/AWS SM — **no** Stripe keys, Supabase service JWTs, JADE keys in code or logs; pre-commit + CI secret scan (gitleaks). | scaffold week 1 |
| S3.2 | **PII never hits structured logs.** Sentry (SaaS, US/EU) may see stack traces — configure `before_send` scrubber + server-side data scrubbing so case text, party names, emails never leave app-side `audit_log`. Or pin Sentry to a Sydney ingest region if available. This is the last realistic cross-border leak in the stack. | `observability.py` scrubber + unit test |
| S3.3 | Outbound network allow-list at the egress level (not just tests): API/worker egress to `api.nswcaselaw` hosts, FRL OData, JADE, Stripe, SendGrid, Bedrock ap-southeast-2 only. austlii.edu.au can never be reached even by mistake (backs G7 at the infra layer). | Fly.io/Egress config; TEST_PLAN G7 |
| S3.4 | Upload validation: PDF/DOCX parsing with pymupdf (AGPL — fine for SaaS, note it) executed in the arq worker, size/mime limits, no parsing in web container. | intake module |

## Gate mapping for @testing

- S1.1/S1.2/S1.5 → `test_bedrock_config` (redefine assertions per S1.1)
- S1.3 → new gate: **G8 modelId/profile allow-test** (no cross-region profile IDs anywhere)
- S1.4 → residency allow-list test (TEST_PLAN P3) + new IAM-policy assertion test
- S2.2/S2.4 → G1 family (`test_rls_case_isolation` extended to child tables + RLS-enabled scan)
- S3.1 → gitleaks CI step; S3.2 → new unit test on the Sentry scrubber

Open items for @compliance: sign off S1.5(b) metadata-only vs full-content Bedrock logging, and whether `audit_log` needs deterministic encryption at rest beyond Postgres-level KMS for LPP review purposes.

## Scaffold findings implemented (30 Aug, verified by test/DB probe — listed in patch order)

| # | Finding (verified live) | Fix landed |
|---|--------------------------|------------|
| F1 | **`audit_content` was mutable/deletable** — probed directly: UPDATE/DELETE succeeded. The LPP full-text trail from checklist 3.2 had append-only protection on `audit_log` only. | Mirrored append-only triggers + REVOKE onto `audit_content`; RLS enabled with NO owner policy (verbatim prompts are service-role-only, not tenant-readable). New gate tests: `test_audit_content_update_rejected` / `..._delete_rejected` |
| F2 | **`test_audit_append_only.py` default DSN points at :5432** — on this machine that's a *different project's* Postgres (self-hosted-ai-starter-kit). It "passed" only because that DB rejected the password. Any same-credentials Postgres listening on 5432 would make the audit tests silently run against foreign state. | Always pin `LEXSIM_TEST_DATABASE_URL=...:5434/lexsim` (compose dev port); documented per @testing's v1.1 note |
| F3 | **RLS silent bypass via superuser DSN.** `app/db.py` engine connects as `postgres` (superuser, `rolsuper=t`) — live probe: Alice's JWT read Bob's case (1 row; RLS never applies to a superuser). RLS is *policy-correct* (verified: non-superuser role sees 0 cross-tenant rows, owner sees 1) but the DSN undid it. | `get_db()` now: refuses any request without a verified Bearer JWT (`PermissionError`); verifies signature/aud/exp via pyjwt; injects only verified `sub` into `request.jwt.claims`. Phase-2 TODO: connect as dedicated least-privilege role (never superuser) — that's the complementary half; wiring JWT identity into the connection user is a scaffold task for @coderbot |
| F4 | `pytest.ini_options` had no `compliance` marker registered (UnknownMarkWarning meant the forced-run gate @compliance described wasn't actually enforceable). | Marker registered in `pyproject.toml`; `-m compliance` verifiably selects 6 p0 gates |
| F5 | `get_settings()` is `lru_cache`d but `app/db.py` built its engine at import time earlier than config validation order was guaranteed in some test entry points — no failure observed; flagged for @coderbot to keep engine creation *after* `validate_provider()` on any rewire. | Non-blocking note only |

## S4. Localhost v1 — Ollama stack (added 30 Aug)

| # | Control | Notes (verified live on this machine, Aug 2026) |
|---|---------|--------------------------|
| S4.1 | **Warm-up asserted, not assumed.** `/api/ps` returned `{"models":[]}` on the live daemon — models unload after `keep_alive` expiry, so any "it was loaded yesterday" observation is stale. `/health/llm` must fail unless a warm-up generation succeeded *this boot*; it cannot just 200 on `/api/tags`. | P0 fail-fast endpoint per supervisor's pitfall 1 |
| S4.2 | **Two Ollama daemons / two users.** Live `ps` shows `ollama serve` running as a *different* user and as menu-bar instances — `launchctl setenv` only affects one daemon after restart. Any `OLLAMA_*` fix applied to the shell silently no-ops against the running daemon. Config asserts must probe the daemon itself (`/api/ps`, OPTIONS-with-Origin probe), never trust env/docs. | explains "curl works but my fix didn't take" class of bugs |
| S4.3 | **No browser→Ollama calls, ever.** The FE talks only to FastAPI; Ollama is reached server-side by the api/worker containers (http clients send no `Origin`, so CORS is out of the critical path). Keeps `auth.uid()` JWT the single auth boundary for model access. | `@hey-api/openapi-ts` client covers all FE→API traffic |
| S4.4 | **Never bind `OLLAMA_HOST=0.0.0.0`.** Ollama has zero authentication — on loopback the browser same-origin policy is the only guard; on 0.0.0.0 every container and LAN device can enumerate/pull/delete models and run inference. Also strips Ollama's host-header middleware. Default loopback binding + `host.docker.internal` from compose is correct; verify the daemon binds `127.0.0.1` (a second daemon can rebind otherwise). | Local-only posture: `test_ollama_local_only` extends to assert socket binding is loopback |
| S4.5 | **403 ≠ auth error.** Ollama middleware returns a bare 403 for disallowed `Origin`/`Host` — looks like auth failure in the browser console. Not applicable if S4.3 holds (server-side calls carry no Origin), but any debug tooling / Playwright page that does hit `:11434` from a browser context will trip it. Documented so it's not misdiagnosed as a security incident. | prefers S4.3 anyway |
| S4.6 | **v1 LPP posture is the strongest config, keep it in writing:** prompts never leave the machine (Ollama loopback), no third-party log/telemetry sink for model content in v1; APP 8 is satisfied by construction. Bedrock config (S1) stays asserted-but-dormant via the `test_bedrock_region_pinned` startup guard so the Phase 2 swap can't regress it. | pairs with checklist 3.3 / gate 2.1 |