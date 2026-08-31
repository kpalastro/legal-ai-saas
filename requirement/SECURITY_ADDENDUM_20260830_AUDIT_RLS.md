# Security addendum to TECH_STACK.md — audit-content RLS + the P0 contract test (30 Aug, post-pause session)

**Finding (probed live, then made a permanent gate):** my earlier `ENABLE ROW LEVEL SECURITY` on `audit_content`
was **fail-closed but incomplete** — it had no `lexsim_app` INSERT/SELECT policy, so `app/audit.py`'s
`write_audit_row()` raised `InsufficientPrivilegeError: new row violates row-level security policy` the moment it
ran as the production role. Every existing test passed because they seed as superuser — the same vacuity class
@deploy killed in the isolation suite. **Fixed and migrated:** `audit_content_write_backend` (INSERT WITH CHECK)
+ `audit_content_read_backend` (SELECT) for `lexsim_app` only — no tenant-read policy; tenants still see zero
content rows. Live DB re-probed + migration file now matches, so fresh envs inherit the fix. Note: this policy
must exist *before* the debate engine writes its first real turn, or turn 1 500s on audit write. The
`write_audit_row`-as-app-role test now passes and will catch this class of regression permanently.

**Second gate added — `tests/test_worker_audit_contract.py` (P0, currently failing by design):** the worker's
`run_simulation` placeholder loop runs 9 turns but writes **zero** `audit_log` rows. C1 requires every LLM call
(audit content + metadata, as the app role). This test codifies that requirement; it is the failing-first net for
@supervisor's next PR (`run_simulation` → `get_provider()` + `write_audit_row` per turn + idempotent rehydrate).
Expected end-state after wiring: `32/32` (the placeholder→real swap closes the last red).

**Residue:** the two probe rows from this session's audit write were cleaned through the superuser
replication-role escape hatch (house rule §8.4). Trail state verified clean post-cleanup.