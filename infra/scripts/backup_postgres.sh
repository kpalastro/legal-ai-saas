#!/bin/bash
# Logical backup of the compose/dev Postgres. Production should use managed
# snapshots + PITR; run a restore drill quarterly.
set -euo pipefail

CONTAINER="${PG_CONTAINER:-infra-postgres-1}"
DATABASE="${PG_DATABASE:-lexsim}"
OUT_DIR="${1:-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$OUT_DIR"
FILE="$OUT_DIR/${DATABASE}-${STAMP}.dump"
docker exec "$CONTAINER" pg_dump -U postgres -d "$DATABASE" --format=custom > "$FILE"
echo "backup: $FILE ($(du -h "$FILE" | cut -f1))"
echo "restore: docker exec -i $CONTAINER pg_restore -U postgres -d $DATABASE --clean --if-exists < $FILE"
