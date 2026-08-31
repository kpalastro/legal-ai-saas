# LexSim AI — Current Architecture (31 Aug 2026)

## Runtime topology (localhost v1)

```
                         ┌──────────────────────────────────────┐
                         │        Browser (Chrome/Safari)       │
                         │  Next.js 16.3.3 · React 19 · SSE ES  │
                         └───────────┬──────────────────────────┘
                      :3000 (apps/web)│
               fetch+JWT │            │ EventSource ?token=
                         ▼            ▼
┌───────────────────────────────────────────────────────────────────────┐
│                    apps/api  — FastAPI :8000 (+ arq worker)           │
│                                                                       │
│  middleware: CORS(:3000) · TokenScrubFilter (JWT never in logs)       │
│                                                                       │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────────────┐  │
│  │ routers/     │  │ agents/      │  │ llm/                        │  │
│  │ cases        │→ │ engine.py    │→ │ OllamaProvider /api/chat    │──┼──► Ollama :11434 (host)
│  │ features     │  │ 9-turn FSM   │  │ BedrockProvider (dormant)   │  │    qwen3.5:latest
│  └──────┬───────┘  └──────┬───────┘  └─────────────────────────────┘  │    think:false · num_ctx 32k
│         │                 │                                          │    seed=42 JUDGE only
│         │                 │ write_audit_row() per LLM call           │
│         ▼                 ▼                                          │
│  ┌──────────────────────────────┐   ┌──────────────────────────────┐ │
│  │ citations/ (FRL + NSW Caselaw│   │ documents/ Jinja2 gen        │ │
│  │  AustLII DENY-LISTED (G7)    │   │  G3 hard block · C5 gate     │ │
│  └──────────────────────────────┘   └──────────────────────────────┘ │
│  deadlines/ AU business-day rules    ·    db.py fail-closed JWT→RLS  │
└──────────────┬────────────────────────────────────────────────────────┘
               │  asyncpg with SET LOCAL request.jwt.claims (verified only)
               ▼
┌───────────────────────────────────────────────────────────────────────┐
│                 postgres:17 :5434  —  lexsim                          │
│   tenants: cases · documents · simulations · generated_documents      │
│            deadlines · audit_log · audit_content                      │
│   RLS ENABLED on all tenant tables  (lexsim_app = NOBYPASSRLS)        │
│   triggers: append-only audit · export gates (citations+attest)       │
└───────────────────────────────────────────────────────────────────────┘
  + infra containers: GoTrue :9999 (JWT) · Mailpit :8025 · redis:7 :6379 (arq)
```

## Data-flow: one debate turn

```
POST /cases/{id}/simulate?token=JWT
  → get_db(): decode+verify JWT (HMAC) → SET LOCAL request.jwt.claims
  → run_debate(): DebateState cursor → PROTOCOL[turn]
      → OllamaProvider.complete(role presets: num_ctx/num_predict/samplers, seed for JUDGE)
      → /api/chat {think:false, options{...}} → jina-safe text strip
      → write_audit_row(prompt_text, response_text) → audit_log + audit_content
      → DB trigger enforces append-only (UPDATE/DELETE raise)
  → SSE frame {turn, role, name, content, is_belief_update[, verdict]}
      └── turn 9 verdict: {lower, point, upper, "not legal advice"}
  → persist_result(): simulations.debate_transcript + outcome_prediction
```

## Document export gate (C5) — three independent layers

| Layer | Mechanism | Failure mode |
|---|---|---|
| API 403 | `citation_gate_status()` before returning content | clean JSON error |
| API 409 | `attest` refuses until every citation `verified` | attestation can't bypass |
| DB trigger | `enforce_export_citations` + `enforce_export_attestation` | even a psql client is blocked |
| RLS | tenant visibility filter on every query | cross-tenant read impossible |

## Provider swap (Phase 2)

`LLM_PROVIDER=bedrock` in `.env` → BedrockProvider (Converse API, ap-southeast-2,
`openai.gpt-oss-120b-1:0`). Same `LLMProvider.complete()` contract; `test_bedrock_region_pinned`
fails startup if region ≠ `ap-southeast-2`; account-level AI-services opt-out policy
required before any real case data (`COMPLIANCE_NOTE` in `bedrock.py`).

## Known constraints (v1, deliberate)

- `?token=` in SSE URLs — RFC 6750-discouraged, dev-only; dies with EventSource
  in Phase 2 (fetch ReadableStream or one-time stream ticket).
- postgres role is owner+superuser in dev → owner-bypass RLS allowed for
  migrations; FORCE ROW LEVEL SECURITY is the Phase-2 pre-prod item.
- Deadlines cover the documented rule set (statement_of_claim/correspondence/
  defence per NSW/Federal/VIC Supreme Court) — more courts = more data rows.

## Diagram lineage

Supersedes the diagram in `requirement/ARCHITECTURE.md` (deprecated banner).
Canonical stack detail: `requirement/TECH_STACK.md`.