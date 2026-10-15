#!/usr/bin/env sh
# Local-development PostgreSQL backup only. Production backup needs a reviewed runbook.
set -eu

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
mkdir -p backups
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-backups/sitara-local-${STAMP}.dump}"

if [ -e "$OUT" ]; then
  echo "Refusing to overwrite existing backup: $OUT" >&2
  exit 1
fi

echo "Creating local PostgreSQL custom-format backup: $OUT"
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$OUT"
echo "Backup written to: $OUT"
echo "Verify by restoring to a separate disposable database; this file does not include uploaded files."
