-- 00: set up the auth schema (on template1 so the `gotrue` clone inherits it), set the
-- search_path GoTrue's unqualified queries need, and create the `gotrue` database LAST
-- — CREATE DATABASE clones the template at creation time, so the schema must exist in
-- template1 before this line runs (verified live when ordering was reversed).
\c template1
CREATE SCHEMA IF NOT EXISTS auth;
-- Do NOT set search_path on the postgres ROLE: a role-level setting applies to
-- every database, so it leaked `auth`-first resolution into the app DB and made
-- unqualified CREATE TABLE land in `auth` instead of `public` (dev/CI divergence).
-- Scope it to the GoTrue database only; the app DB is explicitly public-first.
\c lexsim
ALTER DATABASE lexsim SET search_path = public, auth;
CREATE DATABASE gotrue;
ALTER DATABASE gotrue SET search_path = auth, public;
