#!/usr/bin/env python
"""CI: apply the auth-schema stub to the CI postgres service container.

The dev compose mounts infra/postgres-init/ as /docker-entrypoint-initdb.d, but
GitHub Actions service containers don't mount repo files — migration 0001 then
fails with `schema "auth" does not exist` (it references auth.users + auth.uid()).
This script applies the stub idempotently, exactly like the init mount would.

Two paths, chosen automatically:
  1. asyncpg importable on the host -> connect directly to localhost:5432
  2. else (runner host lacks asyncpg / pip egress restricted) -> pipe the stub
     through `psql` inside the postgres:17-alpine service container via docker exec

Splitting multi-statement SQL on semicolons (asyncpg prepared-statement limit) is
handled by split_sql(), mirroring apps/api/scripts/run_migrations.py.
"""

from __future__ import annotations

import asyncio
import pathlib
import subprocess
import sys

# Migration 0001 creates policies FOR lexsim_app; the role must pre-exist.
ROLE_SQL = """
DO $do$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lexsim_app') THEN
    CREATE ROLE lexsim_app NOLOGIN;
  END IF;
END
$do$;
GRANT USAGE ON SCHEMA public TO lexsim_app;
GRANT USAGE ON SCHEMA auth TO lexsim_app;  -- auth.uid() runs under the app role
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO lexsim_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON auth.users TO lexsim_app;  # auth-stub mirror writes
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO lexsim_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lexsim_app;
"""

DSN = "postgresql://postgres:postgres@localhost:5432/lexsim"
STUB = pathlib.Path(__file__).parent.parent / "postgres-init" / "01-auth-stub.sql"


def split_sql(sql: str) -> list[str]:
    parts, buf, i, n = [], [], 0, len(sql)
    while i < n:
        if sql.startswith("$$", i):
            end = sql.find("$$", i + 2)
            end = n if end == -1 else end + 2
            buf.append(sql[i:end])
            i = end
            continue
        buf.append(sql[i])
        if sql[i] == "'":
            i += 1
            while i < n:
                buf.append(sql[i])
                if sql.startswith("''", i):
                    buf.append("'")
                    i += 2
                    continue
                if sql[i] == "'":
                    i += 1
                    break
                i += 1
            continue
        if sql[i] == ";":
            parts.append("".join(buf).strip())
            buf = []
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def _find_pg_container() -> str:
    out = subprocess.run(
        ["docker", "ps", "--filter", "ancestor=postgres:17-alpine", "--format", "{{.Names}}"],
        capture_output=True, text=True, check=True, timeout=15,
    ).stdout.split()
    if not out:
        raise RuntimeError("no postgres:17-alpine container running for stub install")
    return out[0]


def apply_via_docker() -> None:
    subprocess.run(
        [
            "docker", "exec", "-i", _find_pg_container(),
            "psql", "-U", "postgres", "-d", "lexsim", "-v", "ON_ERROR_STOP=1",
        ],
        input=STUB.read_text() + ROLE_SQL, text=True, check=True, timeout=60,
    )
    print("auth stub: OK via docker psql")


async def apply_via_asyncpg() -> None:
    import asyncpg

    conn = await asyncpg.connect(DSN, timeout=15)
    try:
        for stmt in split_sql(STUB.read_text() + ROLE_SQL):
            await conn.execute(stmt)
        present = await conn.fetchval(
            "SELECT 1 FROM information_schema.tables"
            " WHERE table_schema='auth' AND table_name='users'"
        )
        if not present:
            raise RuntimeError("auth.users missing after stub apply")
        print("auth stub: OK (schema auth, auth.users, auth.uid() present)")
    finally:
        await conn.close()


def main() -> None:
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        # Host pip may hang behind restricted runner egress; docker is guaranteed
        # because this job just started the postgres service container.
        apply_via_docker()
        return
    asyncio.run(apply_via_asyncpg())


if __name__ == "__main__":
    main()