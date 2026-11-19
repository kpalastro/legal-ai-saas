"""0008 — Citation authority snapshots.

Persist what the verifier actually saw (source, URL, snippet, checked_at, hash)
for every citation in a generated draft. This turns a one-off verification into
reproducible evidence and supports LPP/audit reconstruction.

Revision ID: 0008
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")
    op.execute(
        """
        CREATE TABLE public.authority_snapshots (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id UUID NOT NULL REFERENCES public.cases(id) ON DELETE CASCADE,
          raw TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('verified','unverified','flagged')),
          source TEXT NOT NULL,
          url TEXT,
          evidence TEXT,
          checked_at TIMESTAMPTZ,
          content_sha256 TEXT NOT NULL,
          created_at TIMESTAMPTZ DEFAULT NOW(),
          UNIQUE (case_id, raw, content_sha256)
        );
        CREATE INDEX authority_snapshots_case_idx
          ON public.authority_snapshots (case_id, created_at DESC);
        ALTER TABLE public.authority_snapshots ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.authority_snapshots FORCE ROW LEVEL SECURITY;
        CREATE POLICY authority_snapshots_select ON public.authority_snapshots
          FOR SELECT USING (public.case_visible(case_id));
        CREATE POLICY authority_snapshots_insert ON public.authority_snapshots
          FOR INSERT WITH CHECK (public.case_writable(case_id));
        CREATE POLICY authority_snapshots_delete ON public.authority_snapshots
          FOR DELETE USING (public.case_writable(case_id));
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")
    op.execute("DROP TABLE IF EXISTS public.authority_snapshots CASCADE;")
