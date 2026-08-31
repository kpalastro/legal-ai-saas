"""P0 contract test: worker `run_simulation` must write audit rows via the app role.

Two requirements locked here, both currently UNMET by the worker stub (that's the
point — this file is the failing-first net for @supervisor's claimed next PR):

1. `write_audit_row()` (app/audit.py) must succeed when called AS `lexsim_app`
   with that user's claims — i.e. the `audit_content` INSERT path must exist as an
   RLS-allowed app-role path, not just "seeded as superuser" (the vacuity class
   deploy killed in test_rls_isolation.py).
2. `run_simulation()` must persist ≥1 `audit_log` row per LLM turn (C1/G5) —
   the current placeholder loop never touches audit at all, so this assertion is
   the requirement, not a description of today's behaviour.

Marker: compliance. Skips cleanly with no Postgres reachable.
"""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DSN = os.environ.get(
    "LEXSIM_TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5434/lexsim"
)

pytestmark = [pytest.mark.compliance]  # explicit skip logic below (runs only with a DB)

UA = str(uuid.uuid4())
CASE = str(uuid.uuid4())
SIM = str(uuid.uuid4())


def _db_available() -> bool:
    try:
        import asyncio

        async def _ping() -> bool:
            eng = create_async_engine(DSN)
            try:
                async with eng.connect() as c:
                    await c.execute(text("SELECT 1"))
                return True
            except Exception:
                return False
            finally:
                await eng.dispose()

        return asyncio.new_event_loop().run_until_complete(_ping())
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_available(), reason="no Postgres reachable")


async def _seed(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("SET LOCAL ROLE lexsim_app"))  # app role, like prod
        await conn.execute(
            text("SELECT set_config('request.jwt.claims', :c, true)"),
            {"c": f'{{"sub": "{UA}", "role": "authenticated"}}'},
        )
        await conn.execute(text("INSERT INTO auth.users (id) VALUES (:u) ON CONFLICT DO NOTHING"), {"u": UA})
        await conn.execute(
            text("INSERT INTO users (id, email, role) VALUES (:u, :e, 'individual') ON CONFLICT DO NOTHING"),
            {"u": UA, "e": f"audit-{UA[:8]}@test.local"},
        )
        await conn.execute(
            text(
                "INSERT INTO cases (id, user_id, title, jurisdiction, cause_of_action)"
                " VALUES (:c, :u, 'audit contract probe', 'NSW Supreme Court', 'contract_breach')"
                " ON CONFLICT (id) DO NOTHING"
            ),
            {"c": CASE, "u": UA},
        )


async def _cleanup(engine) -> None:
    async with engine.begin() as conn:
        # superuser-only escape hatch, per TEST_PLAN §8 house rule 4
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        await conn.execute(text("DELETE FROM audit_log WHERE case_id = :c"), {"c": CASE})
        await conn.execute(text("SET LOCAL session_replication_role = DEFAULT"))
        await conn.execute(text("DELETE FROM cases WHERE id = :c"), {"c": CASE})
        await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": UA})
        await conn.execute(text("DELETE FROM auth.users WHERE id = :u"), {"u": UA})


@pytest.fixture
async def seeded_engine():
    eng = create_async_engine(DSN)
    await _seed(eng)
    yield eng
    # audit rows are append-only; remove via the superuser escape hatch, same as
    # the RLS suite does (that path existing at all proves only a DBA can tamper).
    async with eng.begin() as conn:
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        await eng.dispose() if False else None
        await conn.execute(
            text("DELETE FROM audit_log WHERE case_id = :c"), {"c": CASE}
        )
        await conn.execute(text("SET LOCAL session_replication_role = DEFAULT"))
        await conn.execute(text("DELETE FROM cases WHERE id = :c"), {"c": CASE})
        await conn.execute(text("DELETE FROM users WHERE id = :u"), {"u": UA})
        await conn.execute(text("DELETE FROM auth.users WHERE id = :u"), {"u": UA})
    await eng.dispose()


@needs_db
class TestWorkerAuditContract:
    async def test_write_audit_row_works_as_app_role(self, seeded_engine) -> None:
        """Regression net for the audit_content INSERT-policy hole @security probed:
        the same code path the worker uses must succeed as lexsim_app, not just
        as the superuser the current tests seed with."""
        from sqlalchemy.ext.asyncio import create_async_engine as _cae  # noqa: F401
        from app.audit import write_audit_row

        eng = create_async_engine(DSN)
        try:
            async with eng.begin() as conn:
                await conn.execute(text("SET LOCAL ROLE lexsim_app"))
                await conn.execute(
                    text("SELECT set_config('request.jwt.claims', :c, true)"),
                    {"c": f'{{"sub": "{UA}", "role": "authenticated"}}'},
                )
                await write_audit_row(
                    conn,  # type: ignore[arg-type]  # AsyncConnection is the real call shape
                    case_id=CASE,
                    user_id=UA,
                    event_type="llm_turn",
                    model_id="qwen3.5:latest",
                    prompt_text="SECURITY-ROLE-PROBE prompt",
                    response_text="SECURITY-ROLE-PROBE response",
                )
        finally:
            await eng.dispose()

    async def test_run_simulation_writes_audit_rows(self, seeded_engine) -> None:
        """Fails-first for the next PR: the placeholder worker stub never calls
        write_audit_row; this test is what forces the wiring (C1/G5)."""
        from worker.main import run_simulation

        result = await run_simulation(ctx={}, case_id=CASE, user_id=UA)
        assert result["case_id"] == CASE
        eng = create_async_engine(DSN)
        try:
            async with eng.begin() as conn:
                await conn.execute(text("SET LOCAL ROLE lexsim_app"))
                await conn.execute(
                    text("SELECT set_config('request.jwt.claims', :c, true)"),
                    {"c": f'{{"sub": "{UA}", "role": "authenticated"}}'},
                )
                n = (
                    await conn.execute(
                        text("SELECT count(*) FROM audit_log WHERE case_id = :c"), {"c": CASE}
                    )
                ).scalar()
        finally:
            await eng.dispose()
        assert n >= 1, (
            f"run_simulation persisted {n} audit rows for case {CASE} — "
            "every LLM turn must write an audit_log row (C1/G5); "
            "placeholder stub must not merge to main once real wiring lands"
        )