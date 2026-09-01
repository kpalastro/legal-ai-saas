#!/usr/bin/env python
"""CI: apply the auth-schema stub + app-role grants to the CI postgres service.

The dev compose mounts infra/postgres-init/ as /docker-entrypoint-initdb.d, but
GitHub Actions service containers don't mount repo files — migration 0001 then
fails with `schema "auth" does not exist` (it references auth.users + auth.uid()
and issues policies FOR lexsim_app). Two modes:

  (default)     apply the auth stub + role creation BEFORE alembic
  --grants-only apply DML grants AFTER alembic (tables/sequences must exist first)

Both are idempotent. Transport chosen automatically: asyncpg if importable, else
`docker exec psql` inside the postgres service container (host pip may hang behind
restricted runner egress; docker is guaranteed — the job started the container).
"""

from __future__ import annotations

import asyncio
import pathlib
import subprocess
import sys

DSN = "postgresql://postgres:postgres@localhost:5432/lexsim"
STUB = pathlib.Path(__file__).parent.parent / "postgres-init" / "01-auth-stub.sql"

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
GRANT SELECT, INSERT, UPDATE, DELETE ON auth.users TO lexsim_app;  -- auth-stub mirror writes
"""

GRANTS = (
    "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO lexsim_app;"
    "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO lexsim_app;"
)


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


def _run_sql_via_docker(sql: str) -> None:
    subprocess.run(
        [
            "docker", "exec", "-i", _find_pg_container(),
            "psql", "-U", "postgres", "-d", "lexsim", "-v", "ON_ERROR_STOP=1",
        ],
        input=sql, text=True, check=True, timeout=60,
    )


async def _run_sql_via_asyncpg(sql: str) -> None:
    import asyncpg

    conn = await asyncpg.connect(DSN, timeout=15)
    try:
        for stmt in split_sql(sql):
            await conn.execute(stmt)
    finally:
        await conn.close()


def _assert_auth_ready() -> None:
    import asyncpg

    async def _check() -> bool:
        conn = await asyncpg.connect(DSN, timeout=15)
        try:
            return await conn.fetchval(
                "SELECT 1 FROM information_schema.tables"
                " WHERE table_schema='auth' AND table_name='users'"
            ) is not None
        finally:
            await conn.close()

    if not asyncio.run(_check()):
        raise RuntimeError("auth.users missing after stub apply")


def install_stub() -> None:
    sql = STUB.read_text() + ROLE_SQL
    try:
        import asyncpg  # noqa: F401
        asyncio.run(_run_sql_via_asyncpg(sql))
    except ImportError:
        # Host pip may hang behind restricted runner egress; docker is guaranteed
        # because this job just started the postgres service container.
        _run_sql_via_docker(sql)
    _assert_auth_ready()
    print("auth stub: OK (schema auth, auth.users, auth.uid(), role lexsim_app)")


def grants_only() -> None:
    """DML grants only — run AFTER alembic (tables/sequences must exist)."""
    sql = GRANTS
    try:
        import asyncpg  # noqa: F401
        asyncio.run(_run_sql_via_asyncpg(sql))
    except ImportError:
        _run_sql_via_docker(sql)
    print("grants: OK")


def main() -> None:
    install_stub()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--grants-only":
        grants_only()
    else:
        main()