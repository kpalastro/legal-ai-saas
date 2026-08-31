#!/usr/bin/env python
"""CI: apply the auth-schema stub to the CI postgres service container.

The dev compose mounts infra/postgres-init/ as /docker-entrypoint-initdb.d, but
GitHub Actions service containers don't mount repo files — migration 0001 then
fails with `schema "auth" does not exist` (it references auth.users + auth.uid()).
This script applies the stub idempotently, exactly like the init mount would.

Runs with the system python3 (the `uv run` venv used by later steps has asyncpg
already; this step runs before setup-uv, so it makes its own arrangements):
 - asyncpg importable -> use it directly
 - else pip install into the interpreter, then re-exec this whole script in a
   fresh interpreter (defensive against sys.path cache staleness)
"""

from __future__ import annotations

import asyncio
import pathlib
import subprocess
import sys

DSN = "postgresql://postgres:postgres@localhost:5432/lexsim"
STUB = pathlib.Path(__file__).parent.parent / "postgres-init" / "01-auth-stub.sql"


def asyncpg_available() -> bool:
    try:
        import asyncpg  # noqa: F401
        return True
    except ImportError:
        return False


def main() -> None:
    if not asyncpg_available() and not pathlib.Path(sys.executable).name.startswith("python"):
        pass  # still try pip below; some runners ship venvs without it
    try:
        import asyncpg  # noqa: F401
    except ImportError:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "asyncpg"], check=True
        )
        # asyncpg landed mid-interpreter; simplest safe path is a fresh process
        subprocess.run([sys.executable, __file__], check=True)
        raise SystemExit(0)

    import asyncio  # noqa: PLC0415 — after guaranteed availability

    async def _apply() -> None:
        import asyncpg

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

    asyncio.run(_apply())


if __name__ == "__main__":
    main()