"""0007 — Document review comments.

Threaded review notes on a generated document version. Writers can create,
resolve and delete; the author can delete their own. RLS follows the document's
case visibility (owner or organisation member).

Revision ID: 0007
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")
    op.execute(
        """
        CREATE TABLE public.document_comments (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id UUID NOT NULL
            REFERENCES public.generated_documents(id) ON DELETE CASCADE,
          user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          body TEXT NOT NULL,
          resolved BOOLEAN NOT NULL DEFAULT FALSE,
          resolved_at TIMESTAMPTZ,
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX document_comments_doc_idx
          ON public.document_comments (document_id, created_at);

        ALTER TABLE public.document_comments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.document_comments FORCE ROW LEVEL SECURITY;
        CREATE POLICY document_comments_select ON public.document_comments
          FOR SELECT USING (EXISTS (
            SELECT 1 FROM public.generated_documents g
            WHERE g.id = document_comments.document_id
              AND public.case_visible(g.case_id)
          ));
        CREATE POLICY document_comments_insert ON public.document_comments
          FOR INSERT WITH CHECK (user_id = auth.uid() AND EXISTS (
            SELECT 1 FROM public.generated_documents g
            WHERE g.id = document_comments.document_id
              AND public.case_writable(g.case_id)
          ));
        CREATE POLICY document_comments_update ON public.document_comments
          FOR UPDATE USING (user_id = auth.uid() OR EXISTS (
            SELECT 1 FROM public.generated_documents g
            WHERE g.id = document_comments.document_id
              AND public.case_writable(g.case_id)
          )) WITH CHECK (user_id = auth.uid() OR EXISTS (
            SELECT 1 FROM public.generated_documents g
            WHERE g.id = document_comments.document_id
              AND public.case_writable(g.case_id)
          ));
        CREATE POLICY document_comments_delete ON public.document_comments
          FOR DELETE USING (user_id = auth.uid() OR EXISTS (
            SELECT 1 FROM public.generated_documents g
            WHERE g.id = document_comments.document_id
              AND public.case_writable(g.case_id)
          ));
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")
    op.execute("DROP TABLE IF EXISTS public.document_comments CASCADE;")
