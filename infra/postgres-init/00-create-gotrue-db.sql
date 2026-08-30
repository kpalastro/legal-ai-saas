-- 00: set up the auth schema (on template1 so the `gotrue` clone inherits it), set the
-- search_path GoTrue's unqualified queries need, and create the `gotrue` database LAST
-- — CREATE DATABASE clones the template at creation time, so the schema must exist in
-- template1 before this line runs (verified live when ordering was reversed).
\c template1
CREATE SCHEMA IF NOT EXISTS auth;
ALTER ROLE postgres SET search_path = auth, public;
\c lexsim
CREATE DATABASE gotrue;
ALTER DATABASE gotrue SET search_path = auth, public;
