"""0005 — Organisations, memberships/RBAC, case sharing, consent records.

Professional-tier tenancy:
  * organisations + memberships (owner/admin/lawyer/paralegal/viewer);
  * cases may belong to an organisation; members see org matters, writers edit;
  * SECURITY DEFINER helpers avoid recursive RLS on membership checks;
  * consents records the APP 5 collection-notice acknowledgement.

Revision ID: 0005
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")

    op.execute(
        """
        CREATE TABLE public.organisations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          name TEXT NOT NULL,
          owner_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE public.memberships (
          org_id UUID NOT NULL REFERENCES public.organisations(id) ON DELETE CASCADE,
          user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          role TEXT NOT NULL CHECK (role IN
            ('owner','admin','lawyer','paralegal','viewer')),
          created_at TIMESTAMPTZ DEFAULT NOW(),
          PRIMARY KEY (org_id, user_id)
        );
        ALTER TABLE public.cases
          ADD COLUMN org_id UUID REFERENCES public.organisations(id) ON DELETE SET NULL;
        CREATE INDEX cases_org_idx ON public.cases (org_id);
        CREATE TABLE public.consents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          consent_version TEXT NOT NULL,
          accepted_at TIMESTAMPTZ DEFAULT NOW(),
          UNIQUE (user_id, consent_version)
        );
        """
    )

    # SECURITY DEFINER helpers: membership checks must not recurse through the
    # memberships RLS policy. They read the caller identity from auth.uid().
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.is_org_member(target_org UUID)
        RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT EXISTS (
            SELECT 1 FROM public.memberships
            WHERE org_id = target_org AND user_id = auth.uid()
          );
        $$;
        CREATE OR REPLACE FUNCTION public.is_org_writer(target_org UUID)
        RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT EXISTS (
            SELECT 1 FROM public.memberships
            WHERE org_id = target_org AND user_id = auth.uid()
              AND role IN ('owner','admin','lawyer','paralegal')
          );
        $$;
        CREATE OR REPLACE FUNCTION public.is_org_admin(target_org UUID)
        RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT EXISTS (
            SELECT 1 FROM public.memberships
            WHERE org_id = target_org AND user_id = auth.uid()
              AND role IN ('owner','admin')
          );
        $$;
        CREATE OR REPLACE FUNCTION public.is_org_owner(target_org UUID)
        RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT EXISTS (
            SELECT 1 FROM public.organisations
            WHERE id = target_org AND owner_id = auth.uid()
          );
        $$;
        CREATE OR REPLACE FUNCTION public.case_visible(target_case UUID)
        RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT EXISTS (
            SELECT 1 FROM public.cases c
            WHERE c.id = target_case
              AND (c.user_id = auth.uid()
                   OR (c.org_id IS NOT NULL AND public.is_org_member(c.org_id)))
          );
        $$;
        CREATE OR REPLACE FUNCTION public.case_writable(target_case UUID)
        RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
          SELECT EXISTS (
            SELECT 1 FROM public.cases c
            WHERE c.id = target_case
              AND (c.user_id = auth.uid()
                   OR (c.org_id IS NOT NULL AND public.is_org_writer(c.org_id)))
          );
        $$;
        """
    )

    op.execute(
        """
        ALTER TABLE public.organisations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.organisations FORCE ROW LEVEL SECURITY;
        CREATE POLICY organisations_select ON public.organisations
          FOR SELECT USING (owner_id = auth.uid() OR public.is_org_member(id));
        CREATE POLICY organisations_insert ON public.organisations
          FOR INSERT WITH CHECK (owner_id = auth.uid());
        CREATE POLICY organisations_update ON public.organisations
          FOR UPDATE USING (owner_id = auth.uid() OR public.is_org_admin(id))
          WITH CHECK (owner_id = auth.uid() OR public.is_org_admin(id));
        CREATE POLICY organisations_delete ON public.organisations
          FOR DELETE USING (owner_id = auth.uid());

        ALTER TABLE public.memberships ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.memberships FORCE ROW LEVEL SECURITY;
        CREATE POLICY memberships_select ON public.memberships
          FOR SELECT USING (public.is_org_member(org_id));
        CREATE POLICY memberships_insert ON public.memberships
          FOR INSERT WITH CHECK (public.is_org_admin(org_id) OR public.is_org_owner(org_id));
        CREATE POLICY memberships_update ON public.memberships
          FOR UPDATE USING (public.is_org_admin(org_id) OR public.is_org_owner(org_id))
          WITH CHECK (public.is_org_admin(org_id) OR public.is_org_owner(org_id));
        CREATE POLICY memberships_delete ON public.memberships
          FOR DELETE USING (public.is_org_admin(org_id) OR public.is_org_owner(org_id));

        CREATE POLICY cases_org_select ON public.cases
          FOR SELECT USING (org_id IS NOT NULL AND public.is_org_member(org_id));
        CREATE POLICY cases_org_write ON public.cases
          FOR ALL USING (org_id IS NOT NULL AND public.is_org_writer(org_id))
          WITH CHECK (org_id IS NOT NULL AND public.is_org_writer(org_id));

        ALTER TABLE public.consents ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.consents FORCE ROW LEVEL SECURITY;
        CREATE POLICY consents_owner ON public.consents
          FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
        """
    )

    for table in (
        "documents",
        "simulations",
        "generated_documents",
        "deadlines",
        "document_chunks",
    ):
        op.execute(
            f"""
            CREATE POLICY {table}_org_select ON public.{table}
              FOR SELECT USING (public.case_visible(case_id));
            CREATE POLICY {table}_org_write ON public.{table}
              FOR ALL USING (public.case_writable(case_id))
              WITH CHECK (public.case_writable(case_id));
            """
        )

    op.execute(
        """
        CREATE POLICY audit_log_org_read ON public.audit_log
          FOR SELECT USING (public.case_visible(case_id));
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")
    op.execute("DROP POLICY IF EXISTS audit_log_org_read ON public.audit_log;")
    for table in (
        "documents",
        "simulations",
        "generated_documents",
        "deadlines",
        "document_chunks",
    ):
        op.execute(f"DROP POLICY IF EXISTS {table}_org_write ON public.{table};")
        op.execute(f"DROP POLICY IF EXISTS {table}_org_select ON public.{table};")
    op.execute(
        """
        DROP POLICY IF EXISTS consents_owner ON public.consents;
        DROP POLICY IF EXISTS cases_org_write ON public.cases;
        DROP POLICY IF EXISTS cases_org_select ON public.cases;
        DROP POLICY IF EXISTS memberships_delete ON public.memberships;
        DROP POLICY IF EXISTS memberships_update ON public.memberships;
        DROP POLICY IF EXISTS memberships_insert ON public.memberships;
        DROP POLICY IF EXISTS memberships_select ON public.memberships;
        DROP POLICY IF EXISTS organisations_delete ON public.organisations;
        DROP POLICY IF EXISTS organisations_update ON public.organisations;
        DROP POLICY IF EXISTS organisations_insert ON public.organisations;
        DROP POLICY IF EXISTS organisations_select ON public.organisations;
        """
    )
    op.execute("DROP TABLE IF EXISTS public.consents CASCADE;")
    op.execute("ALTER TABLE public.cases DROP COLUMN IF EXISTS org_id;")
    op.execute("DROP TABLE IF EXISTS public.memberships CASCADE;")
    op.execute("DROP TABLE IF EXISTS public.organisations CASCADE;")
    op.execute(
        """
        DROP FUNCTION IF EXISTS public.case_writable(UUID);
        DROP FUNCTION IF EXISTS public.case_visible(UUID);
        DROP FUNCTION IF EXISTS public.is_org_owner(UUID);
        DROP FUNCTION IF EXISTS public.is_org_admin(UUID);
        DROP FUNCTION IF EXISTS public.is_org_writer(UUID);
        DROP FUNCTION IF EXISTS public.is_org_member(UUID);
        """
    )
