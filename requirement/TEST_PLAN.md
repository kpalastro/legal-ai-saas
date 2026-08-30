# LexSim AI — QA & Test Plan (v1.1, August 2026)

**Owner:** @testing · **Builds against:** `TECH_STACK.md` v2.1 (localhost v1: Ollama `qwen3.5`, GoTrue, arq via Docker Compose; prod: Bedrock Sydney `gpt-oss-120b`)
**Charter source:** the "Verify-on-localhost" column of `COMPLIANCE_CHECKLIST.md` is the authoritative test charter; this plan adds the plumbing, tiers, and control mapping behind it.
**Rule of engagement:** @coderbot scaffolds from this, not from `ARCHITECTURE.md`'s stale snippets (its `verify_citation()` still targets AustLII — ignore it).

---

## 0.1 Localhost v1 Testing Model (Ollama)

Everything runs on this machine — nothing leaves it, which is itself the best LPP/APP 8 test posture.

### Model tiers by test level

| Level | Model | Why |
|---|---|---|
| Ollama contract/discovery tests | any (`/api/tags` non-empty) | Daemon up, OpenAI-compatible `/v1` alive |
| Fast pytest + arq integration | `qwen3.5-fast:latest` | Speed; personas still exercise full prompts |
| CI smoke / placeholder runs | `qwen3.5:0.8b` | 1 GB; keeps CI seconds-fast |
| Playwright E2E (full intake→debate→export) | `qwen3.5:latest` | Real quality on the money path |

### LLM-nondeterminism rules (v1 and forever)

1. **Never assert on LLM prose.** Tests assert on *structure*: 9 turns in order, JSON schema of verdict (`{lower, point, upper}`), citation-flag enums (❌/⚠️/✅), footer string presence, DB row shapes. `temperature=0` in test runs reduces — not removes — variance.
2. **Determinism lives at the gates, not the model.** SC Gen 23 gates (1.1–1.3, 2.4, 5.2) are DB/server logic — tested with **stubbed provider responses** so gate tests are 100% deterministic. Real-Ollama runs are a separate smoke tier.
3. **Same-fixture dual-provider test (checklist 5.3):** run the same transcript fixture through `OllamaProvider` (live, fast model) and `BedrockProvider` (mocked) → assert byte-identical `audit_log` event shapes. This is the provider-abstraction regression net.
4. **Record-replay for Bedrock:** CI has no AWS. Every Bedrock-conversation test uses recorded Converse fixtures; one nightly smoke uses `LLM_PROVIDER=ollama` against the real daemon as the "live LLM" sanity tier instead.

### Environment specifics

- RLS tests run against **self-hosted GoTrue (:9999)** inside compose — mint two real user A/B JWTs from it; assertions are 0-rows, not 403.
- Email flows (attestation links, reminders) assert against **Mailpit's :8025 API**, not SendGrid.
- Stripe stays test-mode; billing tests use Stripe CLI fixtures, never live keys.

---

## 0. Test Gates (CI must block merge on any of these)

| # | Gate | Level | Blocking? |
|---|------|-------|-----------|
| G1 | RLS tenant isolation — user A can never read user B's cases/documents/simulations | integration | ✅ |
| G2 | Export blocked unless every citation is `✅ Verified` **AND** `user_reviewed = true` **AND** `simulations.user_attestation = true` | integration (DB-level) | ✅ |
| G3 | No affidavit / witness-state­ment / evidentiary-material doc type can be generated — template registry + API + UI all reject | unit + integration | ✅ |
| G4 | Every generated document contains the AI-assistance disclosure footer | unit | ✅ |
| G5 | Audit log is append-only (UPDATE/DELETE rejected) and captures every AI input/output | integration | ✅ |
| G6 | Debate state machine runs exactly the 9-turn protocol; out-of-order turns impossible | unit (state machine) | ✅ |
| G7 | Citation verifiers only hit FRL OData API / NSW Caselaw / JADE — **zero network calls to austlii.edu.au** (tested via HTTP-mock allow/deny list) | integration | ✅ |

G2/G3/G5 are SC Gen 23 / LPP compliance gates — a failure there is a launch blocker, not a bug ticket.

---

## 1. Test Pyramid & Tooling

```
E2E (Playwright)          ~10 scenarios  — auth, intake, live debate (SSE), export gate
Integration (pytest+Asyncio)  ~60        — API + DB + RLS + arq jobs + Bedrock mocked
Unit (pytest / vitest)    ~150+          — state machine, verifiers, templates, Zod schemas
Contract                  per-provider   — FRL / NSW Caselaw / JADE / Bedrock schemas pinned
```

- **Backend:** `pytest` + `pytest-asyncio` + `httpx.AsyncClient` against the app, Postgres 17 + Redis 7 via `docker compose up test-deps`. **No live Bedrock calls in CI** — `boto3` stubbed with recorded fixtures; one nightly smoke tag hits real Bedrock Converse.
- **Frontend:** `vitest` + `@testing-library/react`; SSE stream tested with `MockEventSource`.
- **DB/RLS:** tests run as **two different Supabase JWT identities** in the same DB — assert cross-tenant reads return 0 rows (not 403; RLS silently filters).
- **Contract tests:** `schemathesis` (property-based, from the FastAPI OpenAPI schema) + golden fixtures per external API so a vendor schema change fails loudly.
- **Coverage floor:** 80% lines overall, **100% on** `agents/debate_state_machine.py`, `citations/`, `documents/registry.py`, and the export-gate path. These are the money paths.

---

## 2. Priority Test Matrix (highest risk first)

### P0 — Compliance-critical (SC Gen 23 / APP / LPP)

| Test | What it proves | Level |
|------|----------------|-------|
| `test_rls_case_isolation` | RLS policy `user_id = auth.uid()` filters cross-tenant reads for *every* table on `user_id`/`case_id` chain | integration |
| `test_export_gate_all_conditions` | PDF export raises unless citations all verified + `user_reviewed` + `user_attestation` — test each missing condition independently, assert the CHECK/trigger fires at DB level, not just API level | integration (G2) |
| `test_doc_registry_hard_block` | `docs.generate('affidavit')` → 422; registry enumeration contains no prohibited type; UI route for prohibited type 404s | unit+integration (G3) |
| `test_disclosure_footer_always` | Fuzz every template × doc type → footer substring present | unit (G4) |
| `test_audit_log_append_only` | `UPDATE`/`DELETE` on `audit_log` → permission denied (trigger/privilege); every Bedrock Converse call writes a row with prompt+response refs | integration (G5) |
| `test_bedrock_config` | Converse calls carry no-training/no-retention flags per @security's checklist; invocation logging targets ap-southeast-2 sinks only | unit (config assert) |
| `test_outcome_prediction_is_range` | Prediction API always returns calibrated range + "not legal advice" copy — **never** a bare point estimate (ACL s18/s29) | unit |

### P1 — Core product correctness

| Test | What it proves |
|------|----------------|
| `test_nine_turn_protocol` | State machine: all 9 turns in order, judge belief updates at turns 3/6/9, invalid transitions rejected, pause/intervention resumes at correct turn |
| `test_debate_sse_stream` | Simulated debate streams events in order over SSE; client reconnect resumes from `Last-Event-ID`; no duplicate turns |
| `test_arq_job_idempotency` | Simulation job re-run after failure doesn't duplicate turns or double-bill; retries capped |
| `test_citation_verifier_statuses` | Verifier returns ❌ fake / ⚠️ unverified / ✅ verified against recorded FRL + NSW Caselaw fixtures; hallucination score = fakes/total; `safe_to_file` only <5% |
| `test_verifier_network_deny_list` | All outbound HTTP from `citations/` resolves only to allow-listed hosts; austlii.edu.au in deny list (G7) |
| `test_deadline_calculator` | NSW/VIC/QLD public holidays + weekends correct for all doc types; deterministic fixture dates |
| `test_intake_extraction` | Party/cause-of-action extraction from golden PDFs/DOCX (pymupdf/python-docx); malformed uploads → clean 400 |
| `test_schema_catches_regression` | Alembic migration test asserting `users` table has NO `clerk_user_id` column and `cases.user_id` references `auth.users`-shaped UUID (guards compliance gap #1) |

### P2 — E2E journeys (Playwright)

1. Signup (Supabase email) → login → case intake wizard → attestation checkbox required
2. Upload PDF → timeline → start simulation → watch 9-turn debate stream live (SSE) → pause → intervene → resume
3. Generate Written Submissions → citation table shows statuses → confirm each citation → attestation → export PDF succeeds
4. **Negative export:** same flow but skip one citation confirmation → export button disabled + API 403
5. Prohibited doc type unreachable in UI for AU jurisdiction
6. Stripe test mode: pay-per-case unlock + lawyer subscription

### P3 — Non-functional

- **Load:** simulation stream with 50 concurrent SSE viewers (k6); arq worker throughput ≥ 20 concurrent debates.
- **Latency budgets (from ARCHITECTURE.md):** citation verification <10s; SSE first token <2s.
- **a11y:** axe-core on every Playwright page — WCAG 2.1 AA.
- **Residency:** integration assert — no external call leaves ap-southeast-2 allow-list (APP 8 cross-border check).

---

## 3. Environment & Data

| Env | Purpose | Waste policy |
|-----|---------|--------------|
| `test` (CI) | ephemeral compose: postgres:17 + redis:7 | n/a |
| `staging` | Supabase project + Bedrock **test profile** (separate AWS account), seeded synthetic cases — **never real case data** | nightly reset |
| `prod` | real data — integration tests forbidden; synthetic canary only (fake case → simulate → verify audit row appears) | daily canary |

Fixtures: synthetic legal corpus in `tests/fixtures/legal/` (contracts, Notices to Produce, NCAT orders — all fictional). **No real client documents ever enter the test suite.**

## 4. Entry/Exit Criteria

- **Feature entry:** @coderbot's PR includes tests for its own code; compliance-gate code lands with its gate test in the same PR.
- **Beta launch exit:** G1–G7 green on staging, all P0+P1 passing, P2 journeys green, security audit (Week 10) findings triaged, @compliance's checklist items each traceable to ≥1 test ID.
- **Definition of done for any task:** tests written in the same PR, CI green, no skipped tests left on `main`.

## 5. Traceability — TEST_PLAN ↔ COMPLIANCE_CHECKLIST (1:1 mapping)

Every checklist "Verify-on-localhost" row maps to an owning test ID below; every test maps to a checklist control. G-numbers are the CI gates from §0.

| Checklist | Control | Owning test(s) | Level |
|---|---|---|---|
| 1.1 | Banned doc types | `test_doc_registry_hard_block` (G3), `test_registry_allowlist_exact` (1.6) | unit+integration |
| 1.2 | Citation gate | `test_export_gate_all_conditions` (G2) — per-citation, includes forged-flag case | integration (DB) |
| 1.3 | Attestation gate | `test_export_gate_all_conditions` (attestation=false variant) + Playwright journey 3/4 | integration+e2e |
| 1.4 | Disclosure footer | `test_disclosure_footer_always` (G4) fuzz | unit |
| 1.5 | Range not point-estimate | `test_outcome_prediction_is_range` | unit |
| 2.1 | Sydney pinning | `test_bedrock_region_pinned` (mocked boto3 → startup ValidationError) | unit |
| 2.3 | RBAC roles | `test_role_dashboards` | e2e |
| 2.4 | 7-year purge | `test_purge_expired_cases_idempotent` — old case gone, audit rows intact | integration |
| 2.7, 3.1 | Collection notice + LPP warning | Playwright signup/intake assertions in journey 1 | e2e |
| 3.2 | Append-only audit log | `test_audit_log_append_only` (G5) — app role lacks UPDATE/DELETE | integration |
| 3.3 | Prompts stay local | `test_ollama_local_only` + `test_bedrock_config` (Phase 2) | unit |
| 4.2 | Banned copy | `scripts/check_marketing_copy.py` CI job | CI |
| 4.3 | Hallucination threshold | `test_citation_verifier_statuses` + score→per-citation-review toggle test | unit |
| 5.1 | RLS isolation | `test_rls_case_isolation` (G1) on live GoTrue JWTs + `EXPLAIN` shows policy | integration |
| 5.2 | Server-side re-check | `test_export_gate_all_conditions` (forged body flags ignored) | integration |
| 5.3 | Adapter parity | `test_provider_adapter_parity` (same fixture → identical audit shapes) | unit |
| §6 CI | compliance marker | `.github/workflows/ci.yml`: `pytest -m compliance` forced-run on PRs touching `documents/`, `export`, `rls`, `audit` — path-filter regexp in CI makes skip impossible | CI |

Items 2.2, 2.5, 2.6 are doc/config reviews (no automated test in v1) — tracked on the checklist §3. Every test also carries a back-reference comment: `# REQ: REQUIREMENTS.md §... / SC Gen 23 para ...`.
---

## 7. DB-Backed Compliance Suite (landed 2026-08-30)

`apps/api/tests/test_audit_append_only.py` — 4 tests, marker `compliance`, run against a **real Postgres 17** (compose `postgres` service; `LEXSIM_TEST_DATABASE_URL` env, defaults to localhost:5434-remapped port). CI provisions the same container.

| Test | Proves | Checklist |
|---|---|---|
| `test_audit_update_rejected` | UPDATE on `audit_log` → trigger exception "append-only" — **passes against live DB** | 3.2 / G5 |
| `test_audit_delete_rejected` | DELETE on `audit_log` → trigger exception (seeded probe row first; a zero-row DELETE proves nothing) | 3.2 / G5 |
| `test_audit_content_ref_columns_exist` | `audit_log.content_ref` + `audit_content` table exist — compliance finding #1 (hashes ≠ LPP trail) is schema-enforced | 3.2 |
| `test_full_content_roundtrip` | Full prompt/response bodies reconstructable via `audit_log ⋈ audit_content` in v1 | 3.2 |

**Schema fix shipped with the suite:** migration `0001` originally implemented the G2 export gate's citation check as a table `CHECK` containing a subquery — Postgres rejects this (`cannot use subquery in check constraint`), so the migration failed on first apply. Converted to a `BEFORE INSERT OR UPDATE` trigger `enforce_export_citations()` (same semantics, same error class). Also added `audit_content` + `audit_log.content_ref` per compliance 3.2.

**Helper:** `scripts/run_migrations.py [dsn]` applies raw-SQL migrations to a fresh test DB (splits multi-statement `op.execute` blocks for asyncpg, which rejects multi-command prepared statements). CI uses the same path.

**Setup note for @deploy:** compose postgres host port was remapped to **5434** (5432/5433 already allocated by other stacks on this machine) — env/URLs must follow.
