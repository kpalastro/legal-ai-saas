"""Alembic env: async via asyncpg, migrations applied as the Supabase owner role.
RLS + auth.uid() policies require the migration SQL to run inside Supabase (or a dev
container providing an `auth` schema stub — see infra/docker-compose.yml).

asyncpg (via SQLAlchemy async) rejects multi-command prepared statements, and the
raw-SQL migrations contain multi-statement op.execute blocks. Fix: split any
multi-statement statement at the cursor boundary via a do_execute event listener —
mirrors scripts/run_migrations.py (the dev/test path that has always split)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = None  # raw-SQL migration (op.execute); autogenerate off for 0001


def _split_sql(sql: str) -> list[str]:
    """Split on semicolons not inside $$ blocks or string literals."""
    parts: list[str] = []
    buf: list[str] = []
    i, n = 0, len(sql)
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


class _MultiCommandHandled(Exception):
    """Raised by the do_execute interceptor to signal statements already ran."""


def _do_execute(conn, cursor, statement, parameters, context, executemany):
    stmts = _split_sql(statement)
    if len(stmts) > 1:
        for s in stmts:
            cursor.execute(s, parameters if isinstance(parameters, (tuple, list)) else None)
        # tell SQLAlchemy the statement was handled; its result is not used by
        # raw-SQL migrations (op.execute return values are ignored)
        context._multi_command_handled = True
        return True  # skip default execution
    return False  # fall through to default single-statement execution


def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url)

    async def _run() -> None:
        async with engine.connect() as conn:
            await conn.run_sync(_migrate_on_sync_conn)
            await conn.commit()  # alembic does not commit; DDL+version bump need it
        await engine.dispose()

    asyncio.run(_run())


def _migrate_on_sync_conn(sync_conn) -> None:

    dialect = sync_conn.dialect
    original = dialect.do_execute

    def _do_execute_patched(cursor, statement, parameters, context=None):
        stmts = _split_sql(statement)
        if len(stmts) > 1:
            for s in stmts:
                cursor.execute(s, parameters if isinstance(parameters, (tuple, list)) else None)
            return
        return original(cursor, statement, parameters, context)

    dialect.do_execute = _do_execute_patched
    try:
        context.configure(connection=sync_conn, target_metadata=target_metadata)
        context.run_migrations()
    finally:
        dialect.do_execute = original


if context.is_offline_mode():
    context.configure(url=get_settings().database_url, literal_binds=True)
    context.run_migrations()
else:
    run_migrations_online()