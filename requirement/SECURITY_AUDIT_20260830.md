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

## Addendum — feature-complete round audit (features 4/5/6, `a4c3a9a`)

**Suite 51/51 confirmed on my re-run** (35s, includes the 14 feature+log-filter tests). Reviewed every new security
surface by reading the code + live regex/behavior probes:

| Item | Verdict |
|---|---|
| `log_filter.TokenScrubFilter` (deploy's regression fix for my 31 Aug access-log finding) | ✅ **Approved.** The tuple-args shape they found (uvicorn AccessFormatter builds the request line from `record.args`, so msg-only scrubbing misses the JWT) is a genuine catch — I verified their test suite covers all three record shapes and that arity is preserved post-scrub. The "token value never logged" claim is now design-backed, not log-window luck. |
| Citation module (features 4a) | ✅ Honest-offline default confirmed (unreachable → UNVERIFIED, never fabricated concurrence). Deterministic path, no LLM. |
| G7 deny-list | ✅ `_denylisted()` raises on any austlii URL, and neither outbound URL template (`check_frl`/`check_nsw_caselaw`) can construct an austlii host (verified: 'austlii' appears in the module only inside the denylist tuple). **Gap:** no *test file* yet asserts the deny-list tripwire or exercises `check_frl`/`check_nsw_caselaw` (only `extract_citations` has tests) — the tripwire is live code with zero test coverage. G7 in TEST_PLAN.md explicitly asked for a "HTTP-mock allow/deny list" test; it doesn't exist yet. |
| C5 gate (3-layer) | ✅ API 403 export / 409 attest-until-verified / DB triggers all independently enforce the same three conditions; `attest` 409s on unverified citations (attestation can't bypass verification) — matches @compliance's SC Gen 23 read. |
| XSS in rendered docs | ✅ Probed: Jinja2 `autoescape=True` holds — `<script>` payload renders as `&lt;script&gt;` in the filed document. Templates cannot be user-supplied (dict of 5 pinned templates). |
| Deadline calculator | ✅ NSW holidays (ANZAC, Christmas, Boxing Day) asserted; unknown rule → 422 shape; disclaimers present per DoNotPay precedent. |
| Billing test-mode | ✅ Amounts match REQUIREMENTS.md pricing table; 422 on unknown plan; no Stripe secret in v1 (nothing to leak). |

**Open security item (small, non-blocking):** G7 deny-list tripwire tests — the deny-list enforcement exists in
`app/citations/service.py` but has no test coverage yet; the G7 TEST_PLAN gate expects an HTTP-mock allow/deny
list test. Hand-off suggestion: @testing add `test_g7_denylist_tripwire` (assert `_denylisted()` raises, assert
check_frl/check_nsw_caselaw reject injected austlii URLs) and a mocked-client test that offline sources still
yield UNVERIFIED, never VERIFIED. Everything else in the feature-complete claim is independently verified.

## Addendum — examples-content citation audit (31 Aug late)

Swept all four example folders with the same medium-neutral/act regexes the production verifier uses:

- **Disclosure footers: present** on every chronology + correspondence (9 matches); `not_legal_advice: true` in
  every MANIFEST + verdict note; zero `austlii` tokens anywhere in the content. Good.
- **One hallucination-style citation found in shipped example content:**
  `civil_negligence_compensation/02_written_submissions.txt` line 48 cites
  **"Adeels Palace v Moubarak [2014] NSW 687"** — that's not a real citation. The real chain is
  *Adeels Palace Pty Ltd v Moubarak* [2009] NSWCA 7, affirmed [2010] HCA 31; `[2014] NSW 687` fails the
  medium-neutral court-prefix check entirely ("NSW" alone isn't a court code, and the year/case number don't
  resolve). Textbook exactly-the-risk SC Gen 23 para 17 exists for.
- One borderline-malformed ref in `criminal_assault/02_written_submissions.txt`:
  "*RPS v R* [2019] NSWCA" — missing the case number (and RPS v R is [2000] HCA 3; a 2019 NSWCA ref is suspect).
- **Irony noted for the demo:** the negligence case (the one carrying the hallucinated cite) is *the* showcase for
  the verification pipeline — the production `verify_citations()` would mark `[2014] NSW 687` as
  **UNVERIFIED** (well-formed-enough to extract, but NSW Caselaw has no such match), exactly the behavior we want
  users to see. The examples were generated through the pipeline but bypassed the citation-verification step
  (no `CITATION VERIFICATION RECORD` block in the submissions), so the hallucinated cite shipped unflagged.

**Required fix (small, either owner):** re-run the two affected submissions through `verify_citations()` and
either attach the citation-status block (showing ❌/⚠️) or correct the citations to the real
[2009] NSWCA 7 / [2010] HCA 31 + [2000] HCA 3 forms — OR add a line to `requirement/examples/README.md`
acknowledging these are deliberate hallucination exhibits (honest, but must be labelled as such — currently the
README claims they "surface uncertainty rather than invent case names", which line 48 of the negligence file
contradicts). For a demo that leans on "we dodge hallucinated citations", shipping an unflagged invented cite in
the showcase material undercuts the pitch.

**RESOLVED (coderbot took option (a)) — accepted 31 Aug.** Sidecar `.citations.json` files committed next to both
submissions, generated via the production `verify_citations()` path. I reproduced all three claims independently
through the same production code (offline run): `[2014] NSW 687` → `unverified` ✓; truncated `[2019] NSWCA` not
extracted at all ✓ (gap confirmed — regex needs the trailing number; one-line fix for the verifier follow-up);
nothing claims `verified` offline ✓.

**RESOLUTION UPGRADED — supervisor's verifier refinements (9ec2994) accepted 31 Aug.** Both backlog notes landed,
plus one beyond the ask that I independently verified live through the production path (62/62 my re-run):
truncated `[2019] NSWCA` now extracted → `flagged` ✓; fabricated-court `[2014] NSW 687` upgraded to `flagged`
via the 24-form court allowlist (more truthful than unverified for an invalid form — pre-HTTP, correct) ✓;
deny tokens (`[2024] AUSTLII 1`, `austlii.edu.au`) no longer extracted at all — deny-at-extraction becomes the
prevention layer, tripwires become containment, and coderbot's template-collision test guards the invariant in
the same CI run ✓; known courts unharmed (`[2024] NSWSC 1101` extracts normally) ✓. Regenerated showcase
sidecars confirm: negligence shows `[2014] NSW 687 → flagged` + honest unverified Act rows; criminal shows
`[2019] NSWCA → flagged`. The showcase now exhibits all three citation statuses the product defines, including a
real hallucination flagged by the product's own verifier — the strongest possible G7 narrative for the demo.
Two-layer design (deny-at-extraction = prevention, check_frl/check_nsw_caselaw tripwires = containment) is the
final accepted architecture; any refactor that re-emits deny tokens fails coderbot's test in the same run.

## Audit status summary (as of 31 Aug EOD)

All security findings from 30–31 Aug rounds are closed or tracked with owners: F1–F5 (audit_content immutability,
DSN pinning, superuser-RLS bypass, compliance marker, engine-init ordering) landed and are test-enforced; G7
deny-list coverage landed (6 tests); TokenScrubFilter approved (covers all uvicorn record shapes); examples
citation audit resolved with the honesty exhibit. Remaining outstanding items, all Phase 2 with named owners in
PENDING.md: FORCE RLS + lexsim_app grant tightening, JWT secret rotation, ?token= → header-safe SSE (or
log-filter dependency removed), least-privilege DB role for prod connections, uvicorn access-log hardening (now
done via TokenScrubFilter — pending only the `?token=` removal itself), CI drift-check self-hosted runner, and
the Bedrock Sydney swap for production.