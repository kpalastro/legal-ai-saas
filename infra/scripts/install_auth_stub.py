#!/usr/bin/env python
"""CI: apply the auth-schema stub to the CI postgres service container.

The dev compose mounts infra/postgres-init/ as /docker-entrypoint-initdb.d, but
GitHub Actions service containers don't mount repo files — the migration then
fails with `schema "auth" does not exist` (migration references auth.users +
auth.uid()). This script does what the init mount does, idempotently.

Runs with the system python3; auto-installs asyncpg if it isn't importable.
"""

from __future__ import annotations

import asyncio
import pathlib
import subprocess
import sys

DSN = "postgresql://postgres:postgres@localhost:5432/lexsim"
STUB = pathlib.Path(__file__).parent.parent / "postgres-init" / "01-auth-stub.sql"


def ensure_asyncpg() -> None:
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "asyncpg"], check=True
        )


async def _apply() -> None:
    import asyncpg  # local import: guaranteed present after ensure_asyncpg()

    conn = await asyncpg.connect(DSN, timeout=15)
    try:
        await conn.execute(STUB.read_text())
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
    ensure_asyncpg()
    asyncio.run(_apply())


if __name__ == "__main__":
    main()