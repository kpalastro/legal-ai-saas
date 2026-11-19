"""0004 — Retrieval chunks, analysis provenance, entitlements/privacy fields.

Adds the next product layer:
  * document_chunks: Postgres full-text retrieval over uploaded materials, so the
    debate is grounded in the *relevant* passages rather than the first N chars.
  * audit_log.prompt_version / model_digest: reproducibility evidence.
  * users.erased_at / cases.erased_at: de-identification tombstones (APP 12/13)
    without deleting the append-only audit trail.
  * deadlines.reminder_sent_at + a due-date index for reminder work.

Revision ID: 0004
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")

    # --- retrieval over uploads -------------------------------------------------
    op.execute(
        """
        CREATE TABLE public.document_chunks (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id UUID NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
          case_id UUID NOT NULL REFERENCES public.cases(id) ON DELETE CASCADE,
          chunk_index INTEGER NOT NULL,
          content TEXT NOT NULL,
          search TSVECTOR GENERATED ALWAYS AS
            (to_tsvector('english'::regconfig, content)) STORED
        );
        CREATE INDEX document_chunks_case_idx
          ON public.document_chunks (case_id, chunk_index);
        CREATE INDEX document_chunks_search_idx
          ON public.document_chunks USING GIN (search);
        ALTER TABLE public.document_chunks ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.document_chunks FORCE ROW LEVEL SECURITY;
        CREATE POLICY document_chunks_via_case ON public.document_chunks
          USING (EXISTS (
            SELECT 1 FROM public.cases
            WHERE cases.id = document_chunks.case_id AND cases.user_id = auth.uid()
          ))
          WITH CHECK (EXISTS (
            SELECT 1 FROM public.cases
            WHERE cases.id = document_chunks.case_id AND cases.user_id = auth.uid()
          ));
        """
    )

    # --- reproducibility + privacy tombstones ----------------------------------
    op.execute(
        """
        ALTER TABLE public.audit_log
          ADD COLUMN prompt_version TEXT,
          ADD COLUMN model_digest TEXT;
        ALTER TABLE public.users ADD COLUMN erased_at TIMESTAMPTZ;
        ALTER TABLE public.cases ADD COLUMN erased_at TIMESTAMPTZ;
        ALTER TABLE public.deadlines ADD COLUMN reminder_sent_at TIMESTAMPTZ;
        CREATE INDEX deadlines_due_reminder_idx
          ON public.deadlines (due_date) WHERE reminder_sent = FALSE;
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")
    op.execute("DROP INDEX IF EXISTS public.deadlines_due_reminder_idx;")
    op.execute(
        """
        ALTER TABLE public.deadlines DROP COLUMN IF EXISTS reminder_sent_at;
        ALTER TABLE public.cases DROP COLUMN IF EXISTS erased_at;
        ALTER TABLE public.users DROP COLUMN IF EXISTS erased_at;
        ALTER TABLE public.audit_log
          DROP COLUMN IF EXISTS model_digest,
          DROP COLUMN IF EXISTS prompt_version;
        """
    )
    op.execute("DROP TABLE IF EXISTS public.document_chunks CASCADE;")
