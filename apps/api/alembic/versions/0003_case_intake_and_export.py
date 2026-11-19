"""0003 — Case intake, document metadata, attestation evidence, indexes.

Closes the gaps found in the product audit:
  * `cases` had nowhere to store the facts, parties, issues, relief or court —
    the debate engine could only see title/jurisdiction/cause_of_action.
  * `documents` (uploads) was never written; add extraction/metadata columns.
  * Attestation was a bare boolean with no who/when evidence.
  * The export trigger skipped the attestation check when `simulation_id` was
    NULL, so a document without a linked simulation bypassed gate G2.
  * No indexes existed at all (only primary keys), so tenant/list queries would
    table-scan at any real volume.

Revision ID: 0003
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")

    # --- case intake: the facts the simulation is supposed to reason about ---
    op.execute(
        """
        ALTER TABLE public.cases
          ADD COLUMN description   TEXT,
          ADD COLUMN parties       JSONB NOT NULL DEFAULT '[]'::jsonb,
          ADD COLUMN issues        JSONB NOT NULL DEFAULT '[]'::jsonb,
          ADD COLUMN relief_sought TEXT,
          ADD COLUMN court         TEXT,
          ADD COLUMN case_number   TEXT;
        """
    )

    # --- uploaded documents: provenance + extracted text for grounding ---
    op.execute(
        """
        ALTER TABLE public.documents
          ADD COLUMN original_filename TEXT,
          ADD COLUMN mime_type         TEXT,
          ADD COLUMN size_bytes        BIGINT,
          ADD COLUMN sha256            TEXT,
          ADD COLUMN extracted_text    TEXT;
        """
    )

    # --- attestation evidence: who attested and when ---
    op.execute(
        """
        ALTER TABLE public.simulations
          ADD COLUMN user_attested_at TIMESTAMPTZ,
          ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'
            CHECK (status IN ('running', 'completed', 'failed'));
        """
    )

    # --- indexes: tenant/list/audit access paths ---
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS cases_user_created_idx
          ON public.cases (user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS documents_case_idx
          ON public.documents (case_id, uploaded_at DESC);
        CREATE INDEX IF NOT EXISTS simulations_case_created_idx
          ON public.simulations (case_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS generated_documents_case_idx
          ON public.generated_documents (case_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS generated_documents_simulation_idx
          ON public.generated_documents (simulation_id);
        CREATE INDEX IF NOT EXISTS deadlines_case_due_idx
          ON public.deadlines (case_id, due_date);
        CREATE INDEX IF NOT EXISTS audit_log_case_created_idx
          ON public.audit_log (case_id, created_at);
        CREATE INDEX IF NOT EXISTS audit_content_created_idx
          ON public.audit_content (created_at);
        """
    )

    # --- keep cases.updated_at honest (it was declared but never maintained) ---
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.touch_updated_at() RETURNS trigger AS $$
        BEGIN
          NEW.updated_at = NOW();
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER cases_touch_updated_at
          BEFORE UPDATE ON public.cases
          FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
        """
    )

    # --- G2: a document cannot be exported without a linked simulation ---
    # The original trigger only checked attestation when simulation_id was set,
    # so a NULL link skipped the gate entirely. Require the link too.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.enforce_export_attestation() RETURNS trigger AS $$
        BEGIN
          IF NEW.exported = TRUE THEN
            IF NEW.simulation_id IS NULL THEN
              RAISE EXCEPTION
                'Export blocked: document has no linked simulation (SC Gen 23 attestation required)';
            END IF;
            IF NOT (SELECT user_attestation FROM public.simulations WHERE id = NEW.simulation_id) THEN
              RAISE EXCEPTION
                'Export blocked: simulation.user_attestation is false (SC Gen 23 attestation required)';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )


def downgrade() -> None:
    op.execute("SET LOCAL search_path = public, auth")
    op.execute("DROP TRIGGER IF EXISTS cases_touch_updated_at ON public.cases;")
    op.execute("DROP FUNCTION IF EXISTS public.touch_updated_at;")
    op.execute("DROP INDEX IF EXISTS public.audit_content_created_idx;")
    op.execute("DROP INDEX IF EXISTS public.audit_log_case_created_idx;")
    op.execute("DROP INDEX IF EXISTS public.deadlines_case_due_idx;")
    op.execute("DROP INDEX IF EXISTS public.generated_documents_simulation_idx;")
    op.execute("DROP INDEX IF EXISTS public.generated_documents_case_idx;")
    op.execute("DROP INDEX IF EXISTS public.simulations_case_created_idx;")
    op.execute("DROP INDEX IF EXISTS public.documents_case_idx;")
    op.execute("DROP INDEX IF EXISTS public.cases_user_created_idx;")
    op.execute(
        """
        ALTER TABLE public.simulations
          DROP COLUMN IF EXISTS status,
          DROP COLUMN IF EXISTS user_attested_at;
        """
    )
    op.execute(
        """
        ALTER TABLE public.documents
          DROP COLUMN IF EXISTS extracted_text,
          DROP COLUMN IF EXISTS sha256,
          DROP COLUMN IF EXISTS size_bytes,
          DROP COLUMN IF EXISTS mime_type,
          DROP COLUMN IF EXISTS original_filename;
        """
    )
    op.execute(
        """
        ALTER TABLE public.cases
          DROP COLUMN IF EXISTS case_number,
          DROP COLUMN IF EXISTS court,
          DROP COLUMN IF EXISTS relief_sought,
          DROP COLUMN IF EXISTS issues,
          DROP COLUMN IF EXISTS parties,
          DROP COLUMN IF EXISTS description;
        """
    )
    # Restore the original (weaker) trigger so downgrade is faithful.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.enforce_export_attestation() RETURNS trigger AS $$
        BEGIN
          IF NEW.exported = TRUE AND NEW.simulation_id IS NOT NULL THEN
            IF NOT (SELECT user_attestation FROM public.simulations WHERE id = NEW.simulation_id) THEN
              RAISE EXCEPTION
                'Export blocked: simulation.user_attestation is false (SC Gen 23 attestation required)';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
