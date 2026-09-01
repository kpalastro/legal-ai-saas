-- Migration 0002: FORCE ROW LEVEL SECURITY on all tenant tables (Phase-2 pre-prod control).
--
-- WHY: postgres is table owner + superuser in the dev stack, and owners bypass RLS
-- unless FORCE is set. Every connection that reaches Postgres with superuser creds
-- (including a misconfigured app) would silently see all tenants' rows. FORCE makes
-- even the owner subject to the policies; migrations use the §8.4
-- session_replication_role = replica escape hatch instead of owner bypass.
--
-- Security checklist §5.1 / TEST_PLAN G1 / audit 20260830 FORCE-RLS item.

ALTER TABLE cases              FORCE ROW LEVEL SECURITY;
ALTER TABLE documents          FORCE ROW LEVEL SECURITY;
ALTER TABLE simulations        FORCE ROW LEVEL SECURITY;
ALTER TABLE generated_documents FORCE ROW LEVEL SECURITY;
ALTER TABLE deadlines          FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_log          FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_content      FORCE ROW LEVEL SECURITY;