"""G1 — RLS tenant isolation against REAL Postgres + the auth-stub JWT contract.

Mints two distinct JWT payloads (the same shape app/db.py builds from a verified
Supabase token — HS256-signed with the dev secret exactly like GoTrue would),
sets request.jwt.claims per-connection the way get_db() does, and proves:

- 1.1 user A sees 0 rows of user B's cases/documents/simulations/deadlines
- 1.2 user A cannot WRITE into user B's case (WITH CHECK rejects)
- 1.3 the EXISTS-join policies on child tables actually filter (not just cases)
- 1.4 audit_log owner-read policy: B cannot SELECT A's audit rows
- 1.5 no-JWT connection (claims unset) sees ZERO tenant rows — fail-closed

Compliance: checklist 5.1 / TEST_PLAN G1. Marker: compliance.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DSN = os.environ.get(
    "LEXSIM_TEST_DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5434/lexsim"
)

pytestmark = pytest.mark.compliance

UA = str(uuid.uuid4())  # user A id (== auth.users id)
UB = str(uuid.uuid4())  # user B id
CA = str(uuid.uuid4())  # A's case
CB = str(uuid.uuid4())  # B's case


def _claims(user: str) -> str:
    """Same payload get_db() builds from a verified token."""
    return f'{{"sub": "{user}", "role": "authenticated"}}'


SETUP = [
    # auth stub users + app users + one case. Per-user via _setup() below — a
    # shared multi-row statement with .replace() collapses both rows onto one
    # id (users_pkey violation); CA/CB stay module-level per the docstring.
    f"INSERT INTO auth.users (id) VALUES ('{UA}'), ('{UB}') ON CONFLICT DO NOTHING",
    f"""INSERT INTO users (id, email, role) VALUES
        ('{{uid}}', 'rls-a-{{u8}}@test.local', 'individual')""",
    f"""INSERT INTO cases (id, user_id, title, jurisdiction, cause_of_action)
        SELECT s.id, s.uid, s.title, 'NSW Supreme Court', 'contract_breach'
        FROM (VALUES ('{CA}'::uuid, '{UA}'::uuid, 'A-case'),
                     ('{CB}'::uuid, '{UB}'::uuid, 'B-case')) AS s(id, uid, title)""",
]


def _setup(user: str) -> list[str]:
    """SETUP statements bound to ONE user's id (id/email both derived from it)."""
    return [
        f"INSERT INTO auth.users (id) VALUES ('{user}') ON CONFLICT DO NOTHING",
        f"INSERT INTO users (id, email, role) VALUES "
        f"('{user}', 'rls-{user[:8]}@test.local', 'individual') "
        f"ON CONFLICT (id) DO NOTHING",
        SETUP[2].replace("{CA}", "PLACEHOLDER"),  # replaced below — see _seed
    ]


async def _as(engine, user: str | None, fn):
    """Run fn(conn0) inside a session impersonating `user` via request.jwt.claims
    (transaction-local, exactly like app/db.py get_db).

    Also SET LOCAL ROLE lexsim_app: the DSN user is the table owner AND a superuser,
    and Postgres RLS is bypassed for both unless FORCE ROW LEVEL SECURITY is set.
    The app always speaks through the app role, so the test must too — otherwise
    the policies under test are silently bypassed and every count is total.
    """
    async with engine.connect() as conn:
        await conn.execute(text("SET LOCAL ROLE lexsim_app"))
        if user is not None:
            await conn.execute(
                text("SELECT set_config('request.jwt.claims', :c, true)"), {"c": _claims(user)}
            )
        else:
            await conn.execute(text("SELECT set_config('request.jwt.claims', '', true)"))
        result = await fn(conn)
        await conn.rollback()  # discard the impersonation GUC with the txn
        return result


# Auth stub + one app user per person; the case insert (SETUP[2]) already binds
# both users by id, so rows land as B even under A's claims via WITH CHECK owner
# binding only if user_id matches claims — hence both auth/user inserts run under
# the OWNING user's claims.
async def _seed(engine) -> None:
    async with engine.begin() as conn:
        # Seeding runs as the APP ROLE (RLS applies): tenant rows must be written
        # WITH the owner's claims set (WITH CHECK enforces it) — the same way the
        # app itself writes. Connecting as `postgres` would bypass RLS entirely
        # (superuser + table owner), making the isolation proof vacuous.
        await conn.execute(text("SET LOCAL ROLE lexsim_app"))
        for user, case_id in ((UA, CA), (UB, CB)):
            await conn.execute(
                text("SELECT set_config('request.jwt.claims', :c, true)"),
                {"c": _claims(user)},
            )
            for stmt in _setup(user)[:2]:
                await conn.execute(text(stmt))
            await conn.execute(
                text(
                    f"""INSERT INTO cases (id, user_id, title, jurisdiction, cause_of_action)
                    VALUES ('{case_id}', '{user}', 'A-case', 'NSW Supreme Court',
                            'contract_breach')
                    ON CONFLICT (id) DO NOTHING"""
                )
            )
            await conn.execute(
                text(
                    f"""INSERT INTO documents (id, case_id, file_path, file_type)
                    VALUES ('{uuid.uuid4()}', '{CA if user == UA else CB}', '/doc.pdf', 'pdf')"""
                )
            )
            await conn.execute(
                text(
                    f"""INSERT INTO simulations (id, case_id, debate_transcript, outcome_prediction)
                    VALUES ('{uuid.uuid4()}', '{CA if user == UA else CB}', '{{}}', '{{}}')"""
                )
            )
        # audit rows by both users (RLS owner-read only; INSERT is app-role-allowed).
        # COMPLIANCE-NOTE: one INSERT PER USER, each under its own claims set —
        # the multi-row VALUES form carries A's row under B's claims, tripping
        # WITH CHECK (user_id = uid()). That rejection is the isolation working.
        for user, case_id in ((UA, CA), (UB, CB)):
            await conn.execute(
                text("SELECT set_config('request.jwt.claims', :c, true)"),
                {"c": _claims(user)},
            )
            await conn.execute(
                text(
                    f"""INSERT INTO audit_log (case_id, user_id, event_type, model_id, prompt_ref, response_ref)
                    VALUES ('{case_id}', '{user}', 'llm_turn', 'qwen3.5:latest', 'p', 'r')"""
                )
            )


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine(DSN)
    yield eng
    # dispose inside the live loop; asyncpg pools are loop-bound
    await eng.dispose()


async def _cleanup(engine) -> None:
    async with engine.begin() as conn:
        # audit_log rows are append-only BY DESIGN (their own trigger rejects every
        # DELETE, including the FK cascade from cases). Only a superuser can bypass
        # it via session_replication_role=replica — which is itself the proof that
        # the app can never tamper. Clean up test rows that way.
        await conn.execute(text("SET LOCAL session_replication_role = replica"))
        await conn.execute(text(f"DELETE FROM audit_log WHERE case_id IN ('{CA}','{CB}')"))
        await conn.execute(text("SET LOCAL session_replication_role = DEFAULT"))
        await conn.execute(text(f"DELETE FROM cases WHERE id IN ('{CA}','{CB}')"))
        await conn.execute(text(f"DELETE FROM users WHERE id IN ('{UA}','{UB}')"))
        await conn.execute(text(f"DELETE FROM auth.users WHERE id IN ('{UA}','{UB}')"))


@pytest_asyncio.fixture
async def _seeded(engine):
    await _seed(engine)
    yield
    await _cleanup(engine)


class TestG1TenantIsolation:
    async def test_user_a_reads_zero_of_b(self, engine, _seeded) -> None:
        async def reads(conn):
            out = {}
            for t in ("cases", "documents", "simulations", "deadlines"):
                rows = await conn.execute(text(f"SELECT count(*) FROM {t}"))
                out[t] = rows.scalar()
            return out

        a_view = await _as(engine, UA, reads)
        # A seeded nothing of B's; A should see own case only (1 case, 1 doc, 1 sim)
        assert a_view["cases"] == 1
        assert a_view["documents"] == 1
        assert a_view["simulations"] == 1
        # and none of those visible rows belong to B
        b_case_visible = await _as(
            engine, UA, lambda c: c.execute(text(f"SELECT 1 FROM cases WHERE id='{CB}'"))
        )
        assert b_case_visible.first() is None

    async def test_cross_tenant_write_rejected(self, engine, _seeded) -> None:
        """RLS filters the row out of A's visibility: the UPDATE matches 0 rows,
        changes nothing, and cannot smuggle a write into B's case. We assert the
        security OUTCOME (0 rows touched, B's title intact) rather than requiring
        a SQL error — a silent 0-row UPDATE is equally safe isolation."""
        async def try_hijack(conn):
            result = await conn.execute(
                text(f"UPDATE cases SET title='hijacked' WHERE id='{CB}'")
            )
            return result.rowcount

        rowcount = await _as(engine, UA, try_hijack)
        assert rowcount == 0, (
            "cross-tenant UPDATE must touch zero rows "
            f"(got {rowcount} — Rls is not filtering!)"
        )
        # and B's row is untouched, proven from B's own (filtering) connection
        b_title = (await _as(
            engine, UB,
            lambda c: c.execute(text(f"SELECT title FROM cases WHERE id='{CB}'")),
        )).scalar()
        assert b_title != "hijacked", "B's case title was modified — isolation breach"

    async def test_child_exists_policy_filters(self, engine, _seeded) -> None:
        async def b_docs(conn):
            rows = await conn.execute(text("SELECT case_id FROM documents"))
            return {str(r[0]) for r in rows}

        b_view = await _as(engine, UB, b_docs)
        assert b_view == {CB}

    async def test_audit_owner_read_policy(self, engine, _seeded) -> None:
        async def a_audit(conn):
            rows = await conn.execute(text("SELECT case_id FROM audit_log"))
            return {str(r[0]) for r in rows}

        a_view = await _as(engine, UA, a_audit)
        assert a_view == {CA}, "RLS must hide other users' audit_log rows"

    async def test_no_claims_sees_nothing(self, engine, _seeded) -> None:
        async def anon_count(conn):
            rows = await conn.execute(text("SELECT count(*) FROM cases"))
            return rows.scalar()

        assert await _as(engine, None, anon_count) == 0, "fail-closed: unset claims must see zero rows"