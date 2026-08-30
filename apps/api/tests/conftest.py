import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

# Compose DB is published on :5434 (infra/docker-compose.yml) to avoid colliding
# with other local postgres containers; default the audit/RLS test DSN there so
# the append-only suite runs green out of the box. Override with
# LEXSIM_TEST_DATABASE_URL when pointing at a different instance.
os.environ.setdefault(
    "LEXSIM_TEST_DATABASE_URL",
    "postgresql+asyncpg://postgres:postgres@localhost:5434/lexsim",
)