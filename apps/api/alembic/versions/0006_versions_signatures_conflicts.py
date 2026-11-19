"""0006 — Document versions/signatures, conflict register.

  * generated_documents gain a version group, supersession link, content hash;
  * signatures records a typed-name signature bound to the content hash;
  * conflicts is a per-organisation conflict-check register.

Revision ID: 0006
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")

    op.execute(
        """
        ALTER TABLE public.generated_documents
          ADD COLUMN version INTEGER NOT NULL DEFAULT 1,
          ADD COLUMN version_group_id UUID,
          ADD COLUMN supersedes_id UUID
            REFERENCES public.generated_documents(id) ON DELETE SET NULL,
          ADD COLUMN superseded BOOLEAN NOT NULL DEFAULT FALSE,
          ADD COLUMN content_sha256 TEXT;
        UPDATE public.generated_documents
          SET version_group_id = id WHERE version_group_id IS NULL;
        CREATE INDEX generated_documents_group_idx
          ON public.generated_documents (version_group_id, version);

        CREATE TABLE public.signatures (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          document_id UUID NOT NULL UNIQUE
            REFERENCES public.generated_documents(id) ON DELETE CASCADE,
          user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          signer_name TEXT NOT NULL,
          content_sha256 TEXT NOT NULL,
          signed_at TIMESTAMPTZ DEFAULT NOW()
        );

        CREATE TABLE public.conflicts (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
          party_name TEXT NOT NULL,
          matter_ref TEXT,
          note TEXT,
          created_by UUID REFERENCES public.users(id) ON DELETE SET NULL,
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE INDEX conflicts_org_idx ON public.conflicts (org_id, created_at DESC);

        ALTER TABLE public.signatures ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.signatures FORCE ROW LEVEL SECURITY;
        CREATE POLICY signatures_select ON public.signatures
          FOR SELECT USING (EXISTS (
            SELECT 1 FROM public.generated_documents g
            WHERE g.id = signatures.document_id
              AND public.case_visible(g.case_id)
          ));
        CREATE POLICY signatures_insert ON public.signatures
          FOR INSERT WITH CHECK (user_id = auth.uid() AND EXISTS (
            SELECT 1 FROM public.generated_documents g
            WHERE g.id = signatures.document_id
              AND public.case_writable(g.case_id)
          ));

        ALTER TABLE public.conflicts ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.conflicts FORCE ROW LEVEL SECURITY;
        CREATE POLICY conflicts_select ON public.conflicts
          FOR SELECT USING (public.is_org_member(org_id));
        CREATE POLICY conflicts_write ON public.conflicts
          FOR ALL USING (public.is_org_writer(org_id))
          WITH CHECK (public.is_org_writer(org_id));
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")
    op.execute("DROP TABLE IF EXISTS public.conflicts CASCADE;")
    op.execute("DROP TABLE IF EXISTS public.signatures CASCADE;")
    op.execute(
        """
        DROP INDEX IF EXISTS public.generated_documents_group_idx;
        ALTER TABLE public.generated_documents
          DROP COLUMN IF EXISTS content_sha256,
          DROP COLUMN IF EXISTS superseded,
          DROP COLUMN IF EXISTS supersedes_id,
          DROP COLUMN IF EXISTS version_group_id,
          DROP COLUMN IF EXISTS version;
        """
    )
