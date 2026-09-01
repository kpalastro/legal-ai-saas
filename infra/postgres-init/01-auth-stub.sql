-- 01: DEV-ONLY stub of the Supabase `auth` contract, living in the APP database (lexsim).
-- Why: migration 0001 does `users.id REFERENCES auth.users(id)` and every RLS policy calls
-- `auth.uid()`. In production those come from hosted Supabase. Locally the real GoTrue owns
-- the *authoritative* auth.users in its own `gotrue` DB (00-*.sql), but the app DB still
-- needs this exact shape so RLS + FK work without cross-DB access.
--
-- Guc compatibility (GoTrue-real): GoTrue sets request.jwt.claim.<key> (SINGULAR) in newer
-- versions and request.jwt.claims (PLURAL, full JSON) in older ones. The app writer (db.py)
-- sends the PLURAL JSON blob. So auth.uid() handles BOTH, plural first:
--     sub := coalesce(
--       (current_setting('request.jwt.claims', true)::jsonb ->> 'sub'),   -- plural JSON
--        current_setting('request.jwt.claim.sub', true)                   -- singular
--     )
-- NEVER deploy this stub — prod uses hosted Supabase Auth.
CREATE SCHEMA IF NOT EXISTS auth;

-- Minimal shape compatible with:  REFERENCES auth.users(id)  (FK from app side).
CREATE TABLE IF NOT EXISTS auth.users (id UUID PRIMARY KEY DEFAULT gen_random_uuid());

CREATE OR REPLACE FUNCTION auth.uid() RETURNS UUID LANGUAGE plpgsql STABLE AS $$
DECLARE
  claims TEXT := current_setting('request.jwt.claims', true);
  single TEXT := current_setting('request.jwt.claim.sub', true);
BEGIN
  IF claims IS NOT NULL AND claims <> '' THEN
    RETURN NULLIF(claims::jsonb ->> 'sub', '')::uuid;
  END IF;
  RETURN NULLIF(single, '')::uuid;
END;
$$;

CREATE OR REPLACE FUNCTION auth.role() RETURNS TEXT LANGUAGE plpgsql STABLE AS $$
DECLARE
  claims TEXT := current_setting('request.jwt.claims', true);
  single TEXT := current_setting('request.jwt.claim.role', true);
BEGIN
  IF claims IS NOT NULL AND claims <> '' THEN
    RETURN NULLIF(claims::jsonb ->> 'role', '')::text;
  END IF;
  RETURN NULLIF(single, '')::text;
END;
$$;

-- 02b (appended by deploy): app role — migration 0001 issues policies FOR lexsim_app,
-- so the role must exist before alembic runs. NOLOGIN (app connects as postgres in
-- dev; prod uses a dedicated connection role via Supabase).
DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lexsim_app') THEN
    CREATE ROLE lexsim_app NOLOGIN;
  END IF;
END
$do$;
