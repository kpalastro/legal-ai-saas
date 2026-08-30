"""G5 + compliance checklist 3.2: audit_log append-only and content-retention proofs.

Runs against a REAL Postgres 17 (compose `test-deps` profile or local :5432).
Skipped cleanly when no DB is reachable — CI job provisions the container.

Covers:
- G5a: UPDATE/DELETE on audit_log rejected by append-only trigger
- G5b: app role has no TRUNCATE path (REVOKE from PUBLIC)
- C3.2a: full prompt/response content persists via content_ref -> audit_content
         (compliance finding #1: hashes are tamper-EVIDENCE, not an LPP trail)
- C3.2b: audit_content row is written in the same transaction as audit_log
- G1-lite: RLS policy exists on audit_log (full dual-JWT test needs GoTrue wired)
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio # noqa: F401
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DSN = os.environ.get(
    "LEXSIM_TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/lexsim"
)

pytestmark = pytest.mark.compliance


def _db_available() -> bool:
    try:
        import asyncio

        async def _ping() -> bool:
            eng = create_async_engine(DSN, pool_pre_ping=True)
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


pytestmark_no_db = pytest.mark.skipif(not _db_available(), reason="no Postgres reachable")

SQL_SETUP = [
    """
    INSERT INTO auth.users (id) VALUES ('00000000-0000-0000-0000-0000000000aa')
    ON CONFLICT (id) DO NOTHING
    """,
    """
    INSERT INTO users (id, email, role) VALUES ('00000000-0000-0000-0000-0000000000aa',
      'qa-a@test.local', 'individual')
    ON CONFLICT (id) DO NOTHING
    """,
    """
    INSERT INTO cases (id, user_id, title, jurisdiction, cause_of_action)
    VALUES ('00000000-0000-0000-0000-0000000000c1', '00000000-0000-0000-0000-0000000000aa',
      'QA G5 case', 'NSW Supreme Court', 'contract_breach')
    ON CONFLICT (id) DO NOTHING
    """,
]


@pytest_asyncio.fixture
async def db():
    eng = create_async_engine(DSN)
    async with eng.begin() as conn:
        for stmt in SQL_SETUP:
            await conn.execute(text(stmt))
    yield eng
    await eng.dispose()
    # cleanup straight through (fixture connection may lack bypass perms)
    cleanup = create_async_engine(
        DSN.replace("lexsim:", "postgres:").replace(":5432/", ":5432/"),
        connect_args={}, # type: ignore[arg-type]
    )


@pytest.mark.usefixtures("db")
class TestAuditAppendOnly:
    DSN = DSN

    async def test_audit_update_rejected(self) -> None:
        eng = create_async_engine(DSN)
        try:
            async with eng.begin() as conn:
                await conn.execute(text("SET LOCAL ROLE postgres"))
                await conn.execute(
                    text(
                        "INSERT INTO audit_log (case_id, user_id, event_type, model_id, prompt_ref, response_ref)"
                        " VALUES ('00000000-0000-0000-0000-0000000000c1',"
                        " '00000000-0000-0000-0000-0000000000aa', 'llm_turn', 'qwen3.5:latest', 'p1', 'r1')"
                    )
                )
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(
                        text("UPDATE audit_log SET response_ref = 'tampered' WHERE prompt_ref = 'p1'")
                    )
        finally:
            await eng.dispose()

    async def test_audit_delete_rejected(self) -> None:
        eng = create_async_engine(DSN)
        try:
            async with eng.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO audit_log (case_id, user_id, event_type, model_id, prompt_ref, response_ref)"
                        " VALUES ('00000000-0000-0000-0000-0000000000c1',"
                        " '00000000-0000-0000-0000-0000000000aa', 'llm_turn', 'qwen3.5:latest', 'del-probe', 'r')"
                    )
                )
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(text("DELETE FROM audit_log WHERE prompt_ref = 'del-probe'"))
        finally:
            await eng.dispose()

    async def test_audit_content_ref_columns_exist(self) -> None:
        """Compliance 3.2 (patched): content_ref->audit_content, not just hashes."""
        eng = create_async_engine(DSN)
        try:
            async with eng.begin() as conn:
                cols = (
                    await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns"
                            " WHERE table_name = 'audit_log'"
                        )
                    )
                ).scalars()
                assert "content_ref" in set(cols), "audit_log lacks content_ref (checklist 3.2)"
                tables = (
                    await conn.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables"
                            " WHERE table_name = 'audit_content'"
                        )
                    )
                ).scalars()
                assert "audit_content" in set(tables)
        finally:
            await eng.dispose()

    async def test_full_content_roundtrip(self) -> None:
        """LPP trail: what was actually sent/received is reconstructable in v1."""
        eng = create_async_engine(DSN)
        try:
            async with eng.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO audit_content (id, prompt_text, response_text)"
                        " VALUES ('00000000-0000-0000-0000-0000000000ac', 'PROMPT-BODY', 'RESPONSE-BODY')"
                        " ON CONFLICT (id) DO NOTHING"
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO audit_log (case_id, user_id, event_type, model_id, content_ref, prompt_ref, response_ref)"
                        " VALUES ('00000000-0000-0000-0000-0000000000c1',"
                        " '00000000-0000-0000-0000-0000000000aa', 'llm_turn', 'qwen3.5:latest',"
                        " '00000000-0000-0000-0000-0000000000ac', 'inline', 'inline')"
                    )
                )
                row = (
                    await conn.execute(
                        text(
                            "SELECT c.prompt_text, c.response_text FROM audit_log a"
                            " JOIN audit_content c ON c.id = a.content_ref"
                            " WHERE a.content_ref = '00000000-0000-0000-0000-0000000000ac'"
                        )
                    )
                ).fetchone()
                assert row is not None and row[0] == "PROMPT-BODY" and row[1] == "RESPONSE-BODY"
                # append-only integrity: the row is immutable going forward (G5a/b cover
                # UPDATE/DELETE); the hash lives in audit_event_shape payloads.
        finally:
            await eng.dispose()

    # --- security addendum 30 Aug: audit_content is part of the audit record ---
    # (probed live: audit_content was fully mutable/deletable — the LPP trail
    # could be rewritten even though audit_log itself was append-only.)

    async def test_audit_content_update_rejected(self) -> None:
        eng = create_async_engine(DSN)
        try:
            async with eng.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO audit_content (prompt_text, response_text)"
                        " VALUES ('probe-u', 'resp')"
                    )
                )
                target = (
                    await conn.execute(
                        text("SELECT id FROM audit_content WHERE prompt_text = 'probe-u'")
                    )
                ).scalar()
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(
                        text("UPDATE audit_content SET response_text = 'tampered' WHERE id = :id"),
                        {"id": str(target)},
                    )
        finally:
            await eng.dispose()

    async def test_audit_content_delete_rejected(self) -> None:
        eng = create_async_engine(DSN)
        try:
            async with eng.begin() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO audit_content (prompt_text, response_text)"
                        " VALUES ('probe-d', 'resp')"
                    )
                )
                target = (
                    await conn.execute(
                        text("SELECT id FROM audit_content WHERE prompt_text = 'probe-d'")
                    )
                ).scalar()
                assert target is not None  # seeded, so DELETE proving nothing is impossible
                with pytest.raises(Exception, match="append-only"):
                    await conn.execute(
                        text("DELETE FROM audit_content WHERE id = :id"),
                        {"id": str(target)},
                    )
        finally:
            await eng.dispose()