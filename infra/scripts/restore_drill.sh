#!/bin/bash
# Restore the newest backup into a scratch database, count tables, then drop it.
# Proves the backup is readable without touching the live database.
set -euo pipefail

CONTAINER="${PG_CONTAINER:-infra-postgres-1}"
SCRATCH="${1:-lexsim_restore_drill}"
BACKUP="$(ls -t backups/*.dump 2>/dev/null | head -1 || true)"

if [ -z "$BACKUP" ]; then
  echo "no backup found — run infra/scripts/backup_postgres.sh first" >&2
  exit 1
fi

echo "drill: restoring $BACKUP into $SCRATCH"
docker exec "$CONTAINER" dropdb -U postgres --if-exists "$SCRATCH"
docker exec "$CONTAINER" createdb -U postgres "$SCRATCH"
# --clean --if-exists: the template DB already contains the `auth` stub schema.
docker exec -i "$CONTAINER" pg_restore -U postgres -d "$SCRATCH" --clean --if-exists < "$BACKUP"
TABLES="$(docker exec "$CONTAINER" psql -U postgres -d "$SCRATCH" -tAc \
  "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'")"
JUDGE="$(docker exec "$CONTAINER" psql -U postgres -d "$SCRATCH" -tAc \
  "SELECT count(*) FROM public.simulations")"
echo "drill: restored ${TABLES} public tables, ${JUDGE} simulation rows — OK"
docker exec "$CONTAINER" dropdb -U postgres "$SCRATCH"
echo "drill: scratch database dropped"
