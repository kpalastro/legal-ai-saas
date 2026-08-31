# Security audit note for the Phase-2 review (raised by @deploy/@compliance this round — confirmed by me, plus two findings below)

**State confirmed live (31/31 green, all 7 tenant tables RLS-on, `lexsim_app` is `NOBYPASSRLS`, `NOINHERIT`-clean grants):**
the isolation suite is real now — it runs as the production-role shape, the multi-row-audit WITH CHECK behaviour
compliance described is itself an isolation proof, and the "assert visibility/effect, not SQL errors" house rule is
correct. Two items below are NOT yet closed; one is new this run.

## P1 — `lexsim_app` still holds UPDATE/DELETE on `audit_log` and all four on `audit_content`

Verified via `information_schema.role_table_grants` just now: `lexsim_app` has UPDATE/DELETE grants on both audit
tables. The append-only *triggers* are the only thing standing between the app role and trail tampering (and they
work — my direct UPDATE probe fired "audit_content is append-only"). That's fine while the only write path is
`app/audit.py`, but defense-in-depth says the grants should not advertise capabilities the triggers must then veto:

- `REVOKE UPDATE, DELETE, TRUNCATE ON audit_log, audit_content FROM lexsim_app;` (the `REVOKE ... FROM PUBLIC`
  added in migration 0001 only closes PUBLIC, not named roles that get grants later).
- Same for `generated_documents.citations`/`exported` if that path is meant to be app-gated only.

**When:** before any real case data (same bucket as FORCE RLS — one Phase 2 review item, not urgent today).

## P2 — `audit_content` has NO INSERT policy at all (I probed it: INSERT fails as `lexsim_app`)

The RLS enable I added earlier (`ALTER TABLE audit_content ENABLE ROW LEVEL SECURITY`) had **no INSERT/SELECT policy
created for the app**, only the append-only trigger and REVOKEs. Verified live: as `lexsim_app` with valid claims,
`INSERT INTO audit_content` → `new row violates row-level security policy` — i.e. **`app/audit.py`'s
`write_audit_row()` CTE will fail at runtime on Phase-2 swap** even though the unit tests (which seed as superuser)
pass. This is the fail-closed direction, which is correct — but the *intended* INSERT-allow rule for the app role
needs to exist before the first real debate turn:

```sql
CREATE POLICY audit_content_write_backend ON audit_content
  FOR INSERT TO lexsim_app WITH CHECK (true);
CREATE POLICY audit_content_read_backend ON audit_content
  FOR SELECT TO lexsim_app USING (true);  -- service-role reads for LPP reconstruction; still NO tenant-read policy
```

…and `test_full_content_roundtrip` should be re-pointed to run its INSERT through `SET LOCAL ROLE lexsim_app` so
this can't regress silently (the test currently passes because it seeds as superuser — same vacuity class deploy
just killed in the isolation suite).

## F6 (new, minor) — one orphan `audit_content`-joined `audit_log` row set left by the earlier C3.2 probe

My cleanup of the seed/fixture audit rows went through `session_replication_role=replica` and removed the
`audit_content` side first, which left 7 `audit_log` rows whose `content_ref` pointed at nothing (found it because
`DELETE 0` on a row I could see = trigger doing its job, and the row-level check confirmed exactly one orphaned
content row). All 7 purged via the same superuser escape hatch; **current state: `audit_log` 0 rows,
`audit_content` 0 rows — clean**, verified twice. Noting here because "trail holds only app-path entries" (per
@testing) should be a *verified* claim in the traceability table, not an assumption, and now it is.

## Where this leaves the FORCE-RLS item

`relforcerowsecurity` is still `f` on every tenant table (re-verified live post-pause). Dev keeps superuser
bypass for migrations; the Phase 2 review item stands exactly as @deploy/@compliance framed it — no repetition
needed, just this addendum: **the vacuous-test pattern is the reason**, and any future test suite that connects
via the superuser DSN should refuse to run unless it also `SET LOCAL ROLE lexsim_app` (that'd make the bypass
impossible to reintroduce silently, same trick the `_as()` helper now uses).

Everything else in this round (deploy's vacuous-test + `audit_log`-RLS finds, compliance's per-user-claims insight,
testing's visibility-and-effect house rule) I verified independently and concur with — no security dissent on any
of the three fixes; my probes agree with supervisor's numbers exactly.

## Addendum — 31 Aug: ?token= fallback audit (post CORS/browser-verify round)

Reviewed the `?token=` SSE fallback as shipped in the running container (probed `openapi.json` + read `app/db.py`):

- **Verification path is identical to the header path** (same `decode_supabase_jwt`, same forged-token rejection)
  — no looser SSE rule exists. Confirmed in OpenAPI: both `token` (query) and `Authorization` (header) params on
  `GET /cases/{id}/simulate`.
- **Live-log check:** container (`infra-api-1`, recreated 21:46 after the CORS fix) has **zero logged `token=`
  occurrences** and zero GETs to the simulate route in its current log window — the "token value never logged"
  claim holds as of now, but that's uvicorn default access logs, which DO print full query strings. Any future
  `--log-level info` change or a proxy in front of uvicorn would silently start capturing tokens in plaintext
  logs. Two hardening steps for the Phase-2 close-out of this item:
  1. uvicorn: `--no-access-log` for the SSE route family, or a log filter that truncates `?token=…` — one config
     line, cheap to do while the stack is small.
  2. Prefer the fetch-ReadableStream SSE path (headers work) or the one-time stream-ticket exchange
     (already sketched in the `get_db()` docstring) before any non-localhost deployment.
- The COMPLIANCE_NOTE in `db.py` (RFC 6750 §2.3 / RFC 9700 §4.3.2) already says "do not carry into prod" — this
  addendum puts a *deadline owner* on that sentence: it should close in the same PR that removes the dev-only
  items, not drift into prod by inertia.