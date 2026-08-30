"""Alembic env: async via asyncpg, migrations applied as the Supabase owner role.
RLS + auth.uid() policies require the migration SQL to run inside Supabase (or a dev
container providing an `auth` schema stub — see infra/docker-compose.yml)."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = None  # raw-SQL migration (op.execute); autogenerate off for 0001


def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().database_url)

    async def _run() -> None:
        async with engine.connect() as conn:
            await conn.run_sync(
                lambda c: context.configure(connection=c, target_metadata=target_metadata)
            )
            await conn.run_sync(lambda _: context.run_migrations())

    asyncio.run(_run())


if context.is_offline_mode():
    context.configure(url=get_settings().database_url, literal_binds=True)
    context.run_migrations()
else:
    run_migrations_online()
