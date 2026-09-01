"""Migration 0002: FORCE ROW LEVEL SECURITY on all tenant tables.

Converted from 0002_force_rls.sql — a raw .sql file that alembic never executed
(only .py versions under versions/ run in `alembic upgrade head`), which is why
CI's fresh DB silently lacked FORCE while dev had it applied manually.

Phase-2 pre-prod control: postgres is table owner + superuser in the dev stack,
and owners bypass RLS unless FORCE is set. Every connection reaching Postgres
with superuser creds (including a misconfigured app) would silently see all
tenants' rows. FORCE makes even the owner subject to the policies; future
migrations must use the §8.4 session_replication_role = replica escape hatch
instead of owner bypass.
"""

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"

TABLES = (
    "cases",
    "documents",
    "simulations",
    "generated_documents",
    "deadlines",
    "audit_log",
    "audit_content",
)


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    # Disabling FORCE restores owner bypass; policies themselves stay enabled.
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")