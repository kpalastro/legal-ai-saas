#!/bin/bash
# Report-only dependency scan. Wire the exit codes into CI once the current
# advisory backlog is triaged and an owner is assigned.
set -uo pipefail
cd "$(git rev-parse --show-toplevel)"

status=0

echo "== Python dependency audit =="
if command -v uvx >/dev/null 2>&1; then
  (cd apps/api && uvx pip-audit) || status=1
else
  echo "uvx not installed; skipping pip-audit"
fi

echo "== Node dependency audit =="
if [ -d apps/web/node_modules ]; then
  (cd apps/web && npm audit --omit=dev --audit-level=high) || status=1
else
  echo "apps/web/node_modules missing; run npm ci first"
fi

echo "== Secret-pattern grep (best effort) =="
! grep -rInE 'sk_live_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA|OPENSSH) PRIVATE KEY-----' \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=.venv \
  --exclude-dir=.next --exclude=*.lock . || status=1

exit "$status"
