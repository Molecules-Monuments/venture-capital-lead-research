#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu
umask 077

# Apply the pending forward SQL migrations in order under a checksum ledger:
# a race-safe advisory lock serialises concurrent runs, each migration's bytes
# are verified against the recorded checksum (a changed or renamed applied
# migration fails closed), and only unregistered ones are applied and recorded.

PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="${1:-$PACKAGE_DIR/.env}"
COMPOSE_FILE="$PACKAGE_DIR/docker-compose.yml"
COMPOSE_PROJECT="vc-lead-research-v3"
EXPECTED_LEDGER=""
ACTUAL_LEDGER=""
case "$ENV_FILE" in
  /*) ;;
  *) ENV_FILE="$PACKAGE_DIR/$ENV_FILE" ;;
esac

compose() {
  docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" \
    --env-file "$ENV_FILE" "$@"
}

cleanup() {
  status="$?"
  trap - EXIT HUP INT QUIT TERM
  [ -z "$EXPECTED_LEDGER" ] || rm -f "$EXPECTED_LEDGER"
  [ -z "$ACTUAL_LEDGER" ] || rm -f "$ACTUAL_LEDGER"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT QUIT TERM

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

cd "$PACKAGE_DIR"
if [ ! -f "$ENV_FILE" ] || [ -L "$ENV_FILE" ]; then
  echo "migration environment must be a regular, non-symlink file: $ENV_FILE" >&2
  exit 1
fi

EXPECTED_LEDGER="$(mktemp "${TMPDIR:-/tmp}/openclaw-expected-migrations.XXXXXX")"
ACTUAL_LEDGER="$(mktemp "${TMPDIR:-/tmp}/openclaw-actual-migrations.XXXXXX")"
tab="$(printf '\t')"

# Construct the complete reviewed ledger before touching the database. This is
# also the compatibility ceiling: an older package must reject a database that
# already contains a migration version it does not know.
for migration_path in migrations/[0-9][0-9][0-9]_*.sql; do
  migration_file="${migration_path##*/}"
  version="${migration_file%%_*}"
  name="${migration_file%.sql}"
  case "$version" in
    *[!0-9]*|'') echo "invalid migration version: $migration_file" >&2; exit 1 ;;
  esac
  checksum="$(sha256_file "$migration_path")"
  begin_count="$(awk '/^[[:space:]]*BEGIN;[[:space:]]*$/ { count++ } END { print count + 0 }' "$migration_path")"
  commit_count="$(awk '/^[[:space:]]*COMMIT;[[:space:]]*$/ { count++ } END { print count + 0 }' "$migration_path")"
  if [ "$begin_count" -ne 1 ] || [ "$commit_count" -ne 1 ]; then
    echo "migration must contain exactly one standalone outer BEGIN and COMMIT: $migration_file" >&2
    exit 1
  fi
  printf '%s\t%s\t%s\n' "$version" "$name" "$checksum" >>"$EXPECTED_LEDGER"
done

snapshot_ledger() {
  output="$1"
  {
    printf '%s\n' '\set ON_ERROR_STOP on'
    printf '%s\n' 'BEGIN;'
    printf '%s\n' 'SELECT pg_advisory_xact_lock(2026071801::bigint) \g /dev/null'
    printf '%s\n' '\set ledger_exists false'
    printf '%s\n' "SELECT (to_regclass('public.schema_migrations') IS NOT NULL) AS ledger_exists \\gset"
    printf '%s\n' '\if :ledger_exists'
    printf '%s\n' 'SELECT version,name,checksum_sha256 FROM schema_migrations ORDER BY version;'
    printf '%s\n' '\endif'
    printf '%s\n' 'COMMIT;'
  } | compose exec -T postgres \
    psql -X -w --quiet --username openclaw_owner --dbname openclaw \
    --tuples-only --no-align --field-separator="$tab" >"$output"
}

snapshot_ledger "$ACTUAL_LEDGER"
while IFS="$tab" read -r stored_version stored_name stored_checksum extra; do
  [ -n "$stored_version" ] || continue
  [ -z "${extra:-}" ] || { echo "malformed schema_migrations ledger row" >&2; exit 1; }
  expected_row="$(printf '%s\t%s\t%s' "$stored_version" "$stored_name" "$stored_checksum")"
  if ! grep -F -x -q "$expected_row" "$EXPECTED_LEDGER"; then
    echo "database contains an unexpected or incompatible migration ledger row: $stored_version" >&2
    exit 1
  fi
done <"$ACTUAL_LEDGER"

for migration_path in migrations/[0-9][0-9][0-9]_*.sql; do
  migration_file="${migration_path##*/}"
  version="${migration_file%%_*}"
  name="${migration_file%.sql}"
  case "$version" in
    *[!0-9]*|'') echo "invalid migration version: $migration_file" >&2; exit 1 ;;
  esac
  checksum="$(sha256_file "$migration_path")"

  begin_count="$(awk '/^[[:space:]]*BEGIN;[[:space:]]*$/ { count++ } END { print count + 0 }' "$migration_path")"
  commit_count="$(awk '/^[[:space:]]*COMMIT;[[:space:]]*$/ { count++ } END { print count + 0 }' "$migration_path")"
  if [ "$begin_count" -ne 1 ] || [ "$commit_count" -ne 1 ]; then
    echo "migration must contain exactly one standalone outer BEGIN and COMMIT: $migration_file" >&2
    exit 1
  fi

  # The transaction-scoped advisory lock serializes every package migrator.
  # The ledger decision is made only after that lock is held, so a waiter sees
  # the preceding commit and cannot race a second application. Remove only the
  # validated outer wrapper, then apply and register in the same transaction.
  {
    printf '%s\n' 'BEGIN;'
    printf '%s\n' 'SELECT pg_advisory_xact_lock(2026071801::bigint);'
    printf '%s\n' '\set ledger_exists false'
    printf '%s\n' '\set migration_applied false'
    printf '%s\n' "SELECT (to_regclass('public.schema_migrations') IS NOT NULL) AS ledger_exists \\gset"
    printf '%s\n' '\if :ledger_exists'
    printf '%s\n' "SELECT EXISTS (SELECT 1 FROM schema_migrations WHERE version = :'version') AS migration_applied \\gset"
    printf '%s\n' "SELECT (NOT EXISTS (SELECT 1 FROM schema_migrations WHERE version = :'version') OR EXISTS (SELECT 1 FROM schema_migrations WHERE version = :'version' AND name = :'name' AND checksum_sha256 = :'checksum')) AS migration_valid \\gset"
    printf '%s\n' '\if :migration_valid'
    printf '%s\n' '\else'
    printf '%s\n' "\\warn 'migration checksum/name mismatch for ' :'name'"
    printf '%s\n' "DO \$migration_guard\$ BEGIN RAISE EXCEPTION 'migration checksum/name mismatch'; END \$migration_guard\$;"
    printf '%s\n' '\endif'
    printf '%s\n' '\endif'
    printf '%s\n' '\if :migration_applied'
    printf '%s\n' '\else'
    sed -e '/^[[:space:]]*BEGIN;[[:space:]]*$/d' \
        -e '/^[[:space:]]*COMMIT;[[:space:]]*$/d' "$migration_path"
    printf '\n'
    printf '%s\n' "SELECT register_schema_migration(:'version', :'name', :'checksum');"
    printf '%s\n' '\endif'
    printf '%s\n' 'COMMIT;'
  } | compose exec -T postgres \
    psql -X -w --username openclaw_owner --dbname openclaw \
    --set=ON_ERROR_STOP=1 --set=version="$version" \
    --set=name="$name" --set=checksum="$checksum" >/dev/null
done

snapshot_ledger "$ACTUAL_LEDGER"
if ! cmp "$EXPECTED_LEDGER" "$ACTUAL_LEDGER" >/dev/null; then
  echo "database migration ledger does not exactly match this release after migration" >&2
  exit 1
fi

echo "Database migrations and immutable checksums serialized and reconciled atomically."
