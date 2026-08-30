"""0002 — Security findings from SECURITY_AUDIT_20260830 (by @security, fixed @coderbot).

S-audit #2 (runtime blocker): audit_content had RLS enabled but NO policy, so the app
role would get `new row violates row-level security policy` on the first real debate
turn's audit write (write_audit_row() inserts content + log atomically). Probes passed
in CI only because tests seeded as superuser — the app role could never reproduce it.

Fix: INSERT + SELECT policies for the app role on audit_content. Deliberately NOT
tenant-readable: audit_content holds verbatim prompts (LPP), so no owner-SELECT policy;
only the backend app role touches it.

S-audit #1 (grants advertise UPDATE/DELETE the design forbids): REVOKE'd here too —
triggers already block, this removes the misleading grant.

Revision ID: 0002
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # App writes the trail (both tables), never reads content back through the app path.
    op.execute(
        """
        CREATE POLICY audit_content_insert_backend ON audit_content
          FOR INSERT WITH CHECK (true);
        CREATE POLICY audit_content_select_app ON audit_content
          FOR SELECT USING (true);
        """
    )

    # S-audit #1: grants shouldn't advertise a path the design forbids. The append-only
    # triggers already block UPDATE/DELETE; this revokes the misleading privilege.
    op.execute(
        """
        REVOKE UPDATE, DELETE, TRUNCATE ON audit_content FROM lexsim_app;
        REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM lexsim_app;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP POLICY IF EXISTS audit_content_insert_backend ON audit_content;
        DROP POLICY IF EXISTS audit_content_select_app ON audit_content;
        GRANT UPDATE, DELETE, TRUNCATE ON audit_content TO PUBLIC;
        GRANT UPDATE, DELETE, TRUNCATE ON audit_log TO PUBLIC;
        """
    )