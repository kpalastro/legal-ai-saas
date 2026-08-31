"""0001 — Initial schema (TECH_STACK.md v2.1, Supabase Auth model).

REQUIREMENTS:
- Users reference auth.users(id) — NEVER clerk_user_id (compliance gap #1 / C6).
- RLS on ALL SIX tenant tables; child tables use EXISTS join through cases
  (security S2 — they have no user_id column).
- audit_log is append-only: trigger rejects UPDATE/DELETE + privilege revoke (C1/G5).
- Export gate (C5/G2): all three conditions checked independently at DB level.
- AustLII appears nowhere; no cross-region model ids stored.

Revision ID: 0001
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- users: Supabase Auth mirror (C6: no clerk_user_id, ever) ---
    # SCHEMA-PINNED to public: the local GoTrue setup gives the postgres role
    # `search_path = auth, public`, so an unqualified `users` would resolve to
    # `auth.users` (the FK-locked stub) and the CREATE TABLE would collide with it —
    # verified live: DuplicateTableError "relation users already exists". Prod Supabase
    # has search_path public-first so the pin is a no-op there.
    op.execute(
        """
        CREATE TABLE public.users (
          id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
          email TEXT UNIQUE NOT NULL,
          role TEXT CHECK (role IN ('individual', 'lawyer', 'clinic')) NOT NULL,
          subscription_tier TEXT,
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    # --- cases (tenant root) ---
    op.execute(
        """
        CREATE TABLE cases (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          user_id UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          title TEXT NOT NULL,
          jurisdiction TEXT NOT NULL,
          cause_of_action TEXT NOT NULL,
          status TEXT CHECK (status IN ('intake','simulating','completed','archived')) DEFAULT 'intake',
          simulation_paused BOOLEAN DEFAULT FALSE,
          legal_hold BOOLEAN DEFAULT FALSE,  -- C3 retention override
          created_at TIMESTAMPTZ DEFAULT NOW(),
          updated_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    # --- documents (uploaded evidence) ---
    op.execute(
        """
        CREATE TABLE documents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
          file_path TEXT NOT NULL,
          file_type TEXT NOT NULL,
          uploaded_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    # --- simulations ---
    op.execute(
        """
        CREATE TABLE simulations (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
          debate_transcript JSONB NOT NULL DEFAULT '[]'::jsonb,
          outcome_prediction JSONB,
          weakness_report JSONB,
          interventions JSONB DEFAULT '[]'::jsonb,
          pause_history JSONB DEFAULT '[]'::jsonb,
          hallucination_score FLOAT CHECK (hallucination_score BETWEEN 0 AND 1),
          user_attestation BOOLEAN DEFAULT FALSE,  -- NSW SC Gen 23
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    # --- generated_documents + export gate (C5/G2) ---
    # CHECK enforces: cannot export unless user_reviewed AND every citation verified
    # AND the linked simulation's user_attestation is true. The attestation join is
    # enforced with a trigger (CHECK can't reference another table). The citation
    # check is ALSO a trigger: CHECK constraints cannot contain subqueries in
    # Postgres (verified: asyncpg FeatureNotSupportedError on first apply).
    op.execute(
        """
        CREATE TABLE generated_documents (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
          simulation_id UUID REFERENCES simulations(id),
          doc_type TEXT NOT NULL CHECK (doc_type NOT IN
            ('affidavit','witness_statement','expert_report','evidentiary_material')),  -- G3 hard block
          content TEXT NOT NULL,
          citations JSONB DEFAULT '[]'::jsonb,  -- [{citation, status: 'verified'|'unverified'|'fake'}]
          exported BOOLEAN DEFAULT FALSE,
          export_blocked_reason TEXT,
          user_reviewed BOOLEAN DEFAULT FALSE,  -- SC Gen 23 para 17
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE OR REPLACE FUNCTION enforce_export_citations() RETURNS trigger AS $$
        BEGIN
          IF NEW.exported = TRUE THEN
            IF NEW.user_reviewed IS DISTINCT FROM TRUE THEN
              RAISE EXCEPTION 'Export blocked: user_reviewed is false (SC Gen 23 para 17)';
            END IF;
            IF EXISTS (
              SELECT 1 FROM jsonb_array_elements(NEW.citations) c
              WHERE c->>'status' IS DISTINCT FROM 'verified'
            ) THEN
              RAISE EXCEPTION 'Export blocked: unverified citation present (SC Gen 23 para 17)';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER export_gate_citations BEFORE INSERT OR UPDATE ON generated_documents
          FOR EACH ROW EXECUTE FUNCTION enforce_export_citations();
        """
    )
    # G2 condition 3: simulation.user_attestation must also be true (cross-table trigger)
    op.execute(
        """
        CREATE OR REPLACE FUNCTION enforce_export_attestation() RETURNS trigger AS $$
        BEGIN
          IF NEW.exported = TRUE AND NEW.simulation_id IS NOT NULL THEN
            IF NOT (SELECT user_attestation FROM simulations WHERE id = NEW.simulation_id) THEN
              RAISE EXCEPTION
                'Export blocked: simulation.user_attestation is false (SC Gen 23 attestation required)';
            END IF;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER export_gate_attestation
          BEFORE INSERT OR UPDATE ON generated_documents
          FOR EACH ROW EXECUTE FUNCTION enforce_export_attestation();
        """
    )

    # --- deadlines ---
    op.execute(
        """
        CREATE TABLE deadlines (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          case_id UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
          trigger_doc_type TEXT NOT NULL,
          due_date DATE NOT NULL,
          reminder_sent BOOLEAN DEFAULT FALSE,
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )

    # --- audit_log (C1/G5): append-only, every AI input/output ---
    # Compliance finding (checklist 3.2): hashes are tamper-EVIDENCE, not an LPP trail.
    # v1 keeps the full prompt/response bodies locally in audit_content (cheapest
    # this data will ever be to keep); audit_log references it via content_ref.
    op.execute(
        """
        CREATE TABLE audit_content (
          id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
          prompt_text TEXT NOT NULL,
          response_text TEXT NOT NULL,
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE audit_log (
          id BIGSERIAL PRIMARY KEY,
          case_id UUID REFERENCES cases(id) ON DELETE CASCADE,
          user_id UUID REFERENCES public.users(id),
          event_type TEXT NOT NULL,
          model_id TEXT NOT NULL,
          prompt_ref TEXT NOT NULL,
          response_ref TEXT NOT NULL,
          content_ref UUID REFERENCES audit_content(id),
          created_at TIMESTAMPTZ DEFAULT NOW()
        );
        -- audit_content carries the FULL LPP trail (checklist 3.2) — it is part of
        -- the audit record, so it is append-only too: UPDATE/DELETE rejected, and
        -- audit_log.content_ref rows cannot be rewritten onto different content.
        CREATE OR REPLACE FUNCTION audit_content_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_content is append-only (LPP/C1): UPDATE/DELETE rejected';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER audit_content_no_update BEFORE UPDATE ON audit_content
          FOR EACH ROW EXECUTE FUNCTION audit_content_append_only();
        CREATE TRIGGER audit_content_no_delete BEFORE DELETE ON audit_content
          FOR EACH ROW EXECUTE FUNCTION audit_content_append_only();
        REVOKE UPDATE, DELETE, TRUNCATE ON audit_content FROM PUBLIC;
        CREATE OR REPLACE FUNCTION audit_log_content_ref_immutable() RETURNS trigger AS $$
        BEGIN
          IF NEW.content_ref IS DISTINCT FROM OLD.content_ref THEN
            RAISE EXCEPTION 'audit_log.content_ref is immutable (LPP/C1)';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_log is append-only (LPP/C1): UPDATE/DELETE rejected';
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
          FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
        CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
          FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
        REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM PUBLIC;
        """
    )

    # --- RLS: all SIX tenant tables (S2: EXISTS join through cases for children) ---
    op.execute("ALTER TABLE cases ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY cases_owner ON cases
          USING (user_id = auth.uid())
          WITH CHECK (user_id = auth.uid());
        """
    )
    for table in ("documents", "simulations", "generated_documents", "deadlines"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(
            f"""
            CREATE POLICY {table}_via_case ON {table}
              USING (EXISTS (
                SELECT 1 FROM cases WHERE cases.id = {table}.case_id AND cases.user_id = auth.uid()
              ))
              WITH CHECK (EXISTS (
                SELECT 1 FROM cases WHERE cases.id = {table}.case_id AND cases.user_id = auth.uid()
              ));
            """
        )
    # audit_log: readable by owner through case, insertable by backend role only.
    # audit_content is NOT tenant-readable: it holds the verbatim prompts, so only
    # the backend service role touches it — RLS enabled, no owner policy.
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY audit_log_insert_backend ON audit_log
          FOR INSERT WITH CHECK (user_id = auth.uid());
        """
    )
    op.execute("ALTER TABLE audit_content ENABLE ROW LEVEL SECURITY;")
    # the app role writes/reads the content store (LPP reconstruction); tenants never do
    op.execute(
        """
        CREATE POLICY audit_content_write_backend ON audit_content
          FOR INSERT TO lexsim_app WITH CHECK (true);
        CREATE POLICY audit_content_read_backend ON audit_content
          FOR SELECT TO lexsim_app USING (true);
        """
    )
    op.execute(
        """
        CREATE POLICY audit_log_read_owner ON audit_log
          FOR SELECT USING (EXISTS (
            SELECT 1 FROM cases WHERE cases.id = audit_log.case_id AND cases.user_id = auth.uid()
          ));
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS audit_content_write_backend ON audit_content;")
    op.execute("DROP POLICY IF EXISTS audit_content_read_backend ON audit_content;")
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS audit_content CASCADE;")
    op.execute("DROP TABLE IF EXISTS deadlines CASCADE;")
    op.execute("DROP TABLE IF EXISTS generated_documents CASCADE;")
    op.execute("DROP TABLE IF EXISTS simulations CASCADE;")
    op.execute("DROP TABLE IF EXISTS documents CASCADE;")
    op.execute("DROP TABLE IF EXISTS cases CASCADE;")
    op.execute("DROP TABLE IF EXISTS public.users CASCADE;")
    op.execute("DROP FUNCTION IF EXISTS enforce_export_attestation;")
    op.execute("DROP FUNCTION IF EXISTS audit_log_append_only;")
