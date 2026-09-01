#!/bin/bash
# CI drift-check (pending item #4): fail when the running api container's /srv/app
# diverges from git HEAD — the "stale container serving old code" gap that bit twice.
#
# Usage:
#   ./drift_check.sh              # compare running container vs git working tree
#   DRIFT_CONTAINER=infra-api-1 ./drift_check.sh
#
# Note on the bash -c heredoc: docker exec needs a single string; the embedded
# newline is intentional and quoted, not a formatting accident.
# Exit 0 = in sync (or nothing running). Exit 1 = drift.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

CONTAINER="${DRIFT_CONTAINER:-infra-api-1}"
# DRIFT_TREE: override the local tree root (CI runner: point at the checked-out
# apps/api from the job's own clone instead of the live deploy checkout).
DRIFT_TREE="${DRIFT_TREE:-}"

if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
  echo "drift-check: $CONTAINER not running — nothing to compare (ok)"
  exit 0
fi

tree_hash() {
  # The image COPYies its build context (apps/api) to /srv (WORKDIR /srv, COPY . .),
  # so both sides hash the same fileset: prune caches, venvs, lockfile, egg-info,
  # OS junk and the Dockerfile itself (image may legitimately differ there).
  find . \( -name "__pycache__" -o -name ".venv" -o -name "uv.lock" -o \
            -name ".pytest_cache" -o -name "*.egg-info" -o -name ".DS_Store" -o \
            -name "Dockerfile" -o -name "tests" -o -name "scripts" \) -prune -o -type f -print0 \
    | LC_ALL=C sort -z | xargs -0 sha256sum 2>/dev/null | awk '{print $1}' | sha256sum | cut -d" " -f1
}

REMOTE_HASH=$(docker exec "$CONTAINER" /bin/sh -c "cd /srv && ls pyproject.toml >/dev/null && $(declare -f tree_hash) && tree_hash" 2>/dev/null || echo "unreadable")
LOCAL_TREE=$(cd "${DRIFT_TREE:-apps/api}" && tree_hash)

echo "local working tree : ${LOCAL_TREE:0:12}"
echo "container /srv/app : ${REMOTE_HASH:0:12}"

case "$REMOTE_HASH" in
  unreadable)
    echo "drift-check: FAIL — container source unreadable at /srv/app (image layout changed?)"
    exit 1
    ;;
  "$LOCAL_TREE")
    echo "drift-check: PASS — container matches api working tree"
    ;;
  *)
    echo "drift-check: FAIL — container is serving stale code. Rebuild with:"
    echo "  docker compose -f infra/docker-compose.yml up -d --build api"
    exit 1
    ;;
esac