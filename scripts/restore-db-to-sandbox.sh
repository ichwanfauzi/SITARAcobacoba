#!/usr/bin/env sh
# Restore a local backup into a separate disposable database, never the app DB.
set -eu

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
BACKUP="${1:-}"
TARGET_DB="${2:-sitara_restore_sandbox}"

if [ -z "$BACKUP" ] || [ ! -f "$BACKUP" ]; then
  echo "Usage: $0 <backup.dump> [sitara_restore_database_name]" >&2
  exit 2
fi
case "$TARGET_DB" in
  sitara_restore_[a-zA-Z0-9_]*) ;;
  *) echo "Restore target must begin with 'sitara_restore_' and contain only letters, numbers, and underscores." >&2; exit 3 ;;
esac

APP_DB="$(docker compose exec -T postgres sh -c 'printf %s "$POSTGRES_DB"' | tr -d '\r')"
if [ "$TARGET_DB" = "$APP_DB" ]; then
  echo "Refusing to restore over the configured application database." >&2
  exit 4
fi

echo "This will drop and recreate local database '$TARGET_DB' if it already exists."
printf "Type RESTORE-SANDBOX to continue: "
read -r CONFIRM
if [ "$CONFIRM" != "RESTORE-SANDBOX" ]; then
  echo "Cancelled."
  exit 5
fi

docker compose exec -T postgres sh -c 'dropdb -U "$POSTGRES_USER" --if-exists "$1"' sh "$TARGET_DB"
docker compose exec -T postgres sh -c 'createdb -U "$POSTGRES_USER" "$1"' sh "$TARGET_DB"
docker compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --no-privileges' sh "$TARGET_DB" < "$BACKUP"
echo "Sandbox restore completed: $TARGET_DB"
echo "This script does not restore uploaded documents and is not a production recovery procedure."
