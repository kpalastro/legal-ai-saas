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
