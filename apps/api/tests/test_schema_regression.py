"""C6 regression guard: no migration ever reintroduces clerk_user_id (TEST_PLAN
`test_schema_catches_regression`, compliance gap #1). Pure static check — comments
stripped first, so only executable DDL/docstrings are inspected."""

import pathlib
import re

MIGRATIONS = pathlib.Path(__file__).parent.parent / "alembic" / "versions"


def _code_only(text: str) -> str:
    # strip comments AND docstrings — guard applies to executed DDL, not prose
    text = re.sub(r"#.*", "", text)
    text = re.sub(r'"""(?:[^"]|"(?!""))*"""', "", text, flags=re.DOTALL)
    return text.lower()


def test_no_clerk_user_id_in_migrations() -> None:
    for f in MIGRATIONS.glob("*.py"):
        assert "clerk" not in _code_only(f.read_text()), (
            f"C6 regression: {f.name} reintroduces Clerk/clerk_user_id — use Supabase Auth "
            "(id UUID REFERENCES auth.users(id)); see SECURITY_CHECKLIST S2 / COMPLIANCE gap #1"
        )


def test_users_table_references_auth_users() -> None:
    initial = (MIGRATIONS / "0001_initial_schema.py").read_text()
    assert "REFERENCES auth.users(id)" in initial


def test_migrations_pin_the_public_schema() -> None:
    """Regression guard for the dev/CI divergence found on 19 Nov 2026: the
    GoTrue role-level search_path made unqualified CREATE TABLE land in `auth`.
    Migrations must pin resolution and explicitly own public.<table>."""
    for name in ("0001_initial_schema.py", "0002_force_rls.py", "0003_case_intake_and_export.py"):
        source = (MIGRATIONS / name).read_text()
        assert "SET LOCAL search_path = public, auth" in source, name
    initial = (MIGRATIONS / "0001_initial_schema.py").read_text()
    for table in ("cases", "documents", "simulations", "generated_documents", "deadlines"):
        assert f"CREATE TABLE public.{table}" in initial, table
