"""QA helper: apply the current alembic migrations to a test DB (used for the
fresh localhost test container; CI provisions the DB the same way).

Usage: .venv/bin/python scripts/run_migrations.py [dsn]

Splits multi-statement op.execute() blocks on ';'-terminated statements —
asyncpg's prepared statements reject multi-command strings.
"""

import asyncio
import importlib.util
import pathlib
import re
import sys

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine


def load_migration(path: str):
    spec = importlib.util.spec_from_file_location("m", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def split_sql(sql: str) -> list[str]:
    """Split on semicolons not inside dollar-quoted blocks or string literals."""
    parts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if sql.startswith("$$", i):
            end = sql.find("$$", i + 2)
            end = n if end == -1 else end + 2
            buf.append(sql[i:end])
            i = end
            continue
        buf.append(ch)
        if ch == "'":
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
        if ch == ";":
            parts.append("".join(buf).strip())
            buf = []
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p and not re.fullmatch(r"[;\s]*", p)]


async def apply(dsn: str) -> None:
    eng = create_async_engine(dsn)
    versions = sorted(pathlib.Path("alembic/versions").glob("*.py"))
    async with eng.connect() as conn:

        def _run(sync_conn):
            ctx = MigrationContext.configure(sync_conn)
            with Operations.context(ctx) as op:
                original_execute = op.execute

                def _execute(sql, *a, **kw):
                    for stmt in split_sql(sql):
                        original_execute(stmt, *a, **kw)

                op.execute = _execute  # type: ignore[method-assign]
                for v in versions:
                    mod = load_migration(str(v))
                    mod.upgrade()

        await conn.run_sync(_run)
        await conn.commit()
    await eng.dispose()
    print(f"Applied {len(versions)} migration(s) to {dsn}")


if __name__ == "__main__":
    dsn = sys.argv[1] if len(sys.argv) > 1 else "postgresql+asyncpg://postgres:postgres@localhost:5434/lexsim"
    asyncio.run(apply(dsn))