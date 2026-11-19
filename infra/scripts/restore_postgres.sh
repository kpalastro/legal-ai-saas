#!/bin/bash
# Restore a logical backup produced by backup_postgres.sh.
# Destructive: --clean --if-exists replaces objects in the target database.
# Take a fresh backup first and run a drill on a scratch database.
set -euo pipefail

CONTAINER="${PG_CONTAINER:-infra-postgres-1}"
DATABASE="${PG_DATABASE:-lexsim}"
FILE="${1:?usage: restore_postgres.sh <backup.dump>}"

[ -f "$FILE" ] || { echo "backup not found: $FILE" >&2; exit 1; }
echo "restoring $FILE into $DATABASE on $CONTAINER"
docker exec -i "$CONTAINER" pg_restore -U postgres -d "$DATABASE" --clean --if-exists < "$FILE"
echo "restore complete — run the smoke checks (health/db, a signup→case→simulate round-trip)"
