#!/bin/sh
# SPDX-License-Identifier: 0BSD
set -eu
umask 077
# Keep lifecycle runs from shedding bytecode caches into the pristine package.
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

# Create one authenticated, self-consistent recovery point: quiesce the
# consumers, dump the database and tar the state/inbox/quarantine trees, then
# write an HMAC-signed checksum manifest (BACKUP_HMAC_KEY) so a later restore can
# prove the bytes are the ones this backup produced. Usage: backup.sh DEST_DIR.

PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="$PACKAGE_DIR/.env"
COMPOSE_FILE="$PACKAGE_DIR/docker-compose.yml"
COMPOSE_PROJECT="openclaw-lead-research-v3"
LOCK_DIR="/tmp/openclaw-lead-research-v3-lifecycle.lock"
# Captured before the cd into the package below: a relative destination must
# resolve where the operator invoked the script, not inside the live package
# tree that recovery points are documented to stay out of.
INVOCATION_PWD="$PWD"
# Document intake snapshots accumulate in the state tier, so its archive bound
# is operator-tunable (check_env.py validates the range). Read before the cd so
# a relative ENV_FILE still resolves.
STATE_ARCHIVE_MAX_BYTES="$(sed -n 's/^OPENCLAW_STATE_ARCHIVE_MAX_BYTES=//p' "$ENV_FILE" 2>/dev/null | head -n 1)"
[ -n "$STATE_ARCHIVE_MAX_BYTES" ] || STATE_ARCHIVE_MAX_BYTES=2147483648
DESTINATION_INPUT="${1:-}"
LEAVE_QUIESCED="${OPENCLAW_BACKUP_LEAVE_QUIESCED:-0}"
COMPATIBLE_BACKUP="${OPENCLAW_BACKUP_COMPATIBLE_LOCK:-0}"
LOCK_OWNED=0
LOCK_TOKEN=""
STAGING=""
LEDGER_SNAPSHOT=""
BACKUP_PACKAGE_VERSION=""
GATEWAY_WAS_RUNNING=0
QUIESCED=0

compose() {
  docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" \
    --env-file "$ENV_FILE" "$@"
}

paths_overlap() {
  case "$1" in
    "$2"|"$2"/*) return 0 ;;
  esac
  case "$2" in
    "$1"|"$1"/*) return 0 ;;
  esac
  return 1
}

sha256_path() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

verify_local_artifacts() {
  inventory="$1"
  inbox_root="$2"
  quarantine_root="$3"
  # vcops writes exactly one artifact URI form into evidence_artifacts:
  # `state://intake-snapshots/<sha>.<ext>` under VCOPS_STATE_ROOT
  # (/home/node/.openclaw/vcops). The state archive is tarred from
  # /home/node/.openclaw, so inside the extracted copy that is vcops/... .
  state_root="$4"
  tab="$(printf '\t')"
  while IFS="$tab" read -r digest tier uri extra; do
    [ -n "$digest" ] || continue
    [ -z "${extra:-}" ] || { echo "malformed local-artifact inventory" >&2; return 1; }
    case "$digest" in
      *[!0-9a-f]*|'') echo "invalid artifact digest in recovery inventory" >&2; return 1 ;;
    esac
    [ "${#digest}" -eq 64 ] || { echo "invalid artifact digest length" >&2; return 1; }
    case "$tier:$uri" in
      workspace_file:state://*) root="$state_root/vcops"; relative="${uri#state://}" ;;
      workspace_file:inbox://*) root="$inbox_root"; relative="${uri#inbox://}" ;;
      workspace_file:/inbox/*) root="$inbox_root"; relative="${uri#/inbox/}" ;;
      quarantine:quarantine://*) root="$quarantine_root"; relative="${uri#quarantine://}" ;;
      quarantine:/quarantine/*) root="$quarantine_root"; relative="${uri#/quarantine/}" ;;
      *) echo "unsupported local artifact URI in database: $tier:$uri" >&2; return 1 ;;
    esac
    case "$relative" in
      ''|/*|..|../*|*/..|*/../*) echo "unsafe local artifact URI: $uri" >&2; return 1 ;;
    esac
    artifact_path="$root/$relative"
    if [ ! -f "$artifact_path" ] || [ -L "$artifact_path" ]; then
      echo "database artifact URI does not resolve to a regular recovery file: $uri" >&2
      return 1
    fi
    actual="$(sha256_path "$artifact_path")"
    if [ "$actual" != "$digest" ]; then
      echo "database artifact hash does not match recovery file: $uri" >&2
      return 1
    fi
  done <"$inventory"
}

cleanup() {
  status="$?"
  trap - EXIT HUP INT TERM
  if [ "$status" -ne 0 ] && [ "$QUIESCED" -eq 1 ] && \
     [ "$GATEWAY_WAS_RUNNING" -eq 1 ] && [ "$LEAVE_QUIESCED" -ne 1 ]; then
    echo "Backup failed; attempting to restore the previously running gateway." >&2
    compose up -d --wait --no-deps openclaw-gateway >/dev/null 2>&1 || true
  fi
  if [ -n "$STAGING" ] && [ -d "$STAGING" ]; then
    rm -rf -- "$STAGING"
  fi
  if [ -n "$LEDGER_SNAPSHOT" ] && [ -f "$LEDGER_SNAPSHOT" ]; then
    rm -f -- "$LEDGER_SNAPSHOT"
  fi
  if [ "$LOCK_OWNED" -eq 1 ]; then
    rm -f "$LOCK_DIR/owner"
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

if [ -z "$DESTINATION_INPUT" ]; then
  echo "usage: $0 NEW_BACKUP_DIRECTORY" >&2
  exit 2
fi
case "$LEAVE_QUIESCED" in
  0|1) ;;
  *) echo "OPENCLAW_BACKUP_LEAVE_QUIESCED must be 0 or 1" >&2; exit 2 ;;
esac
case "$COMPATIBLE_BACKUP" in
  0|1) ;;
  *) echo "OPENCLAW_BACKUP_COMPATIBLE_LOCK must be 0 or 1" >&2; exit 2 ;;
esac
if [ "$COMPATIBLE_BACKUP" -eq 1 ] && \
   { [ -z "${OPENCLAW_LIFECYCLE_LOCK_TOKEN:-}" ] || [ "$LEAVE_QUIESCED" -ne 1 ]; }; then
  echo "compatible-lock backup mode is reserved for a locked, quiesced update" >&2
  exit 2
fi

cd "$PACKAGE_DIR"
./scripts/check_env.sh "$ENV_FILE" >/dev/null
if [ ! -d "$PACKAGE_DIR/inbox" ] || [ -L "$PACKAGE_DIR/inbox" ]; then
  echo "package inbox must be an existing, non-symlink directory" >&2
  exit 1
fi
PACKAGE_INBOX="$(CDPATH= cd -- "$PACKAGE_DIR/inbox" && pwd -P)"

if [ -n "${OPENCLAW_LIFECYCLE_LOCK_TOKEN:-}" ]; then
  if [ ! -f "$LOCK_DIR/owner" ] || [ -L "$LOCK_DIR/owner" ] || \
     [ "$(cat "$LOCK_DIR/owner")" != "$OPENCLAW_LIFECYCLE_LOCK_TOKEN" ]; then
    echo "invalid inherited lifecycle lock token" >&2
    exit 1
  fi
else
  if ! mkdir "$LOCK_DIR"; then
    echo "another lifecycle operation is running or left a stale lock: $LOCK_DIR" >&2
    exit 1
  fi
  LOCK_OWNED=1
  LOCK_TOKEN="backup:$$"
  printf '%s\n' "$LOCK_TOKEN" >"$LOCK_DIR/owner"
fi

case "$DESTINATION_INPUT" in
  /*) ;;
  *) DESTINATION_INPUT="$INVOCATION_PWD/$DESTINATION_INPUT" ;;
esac
DESTINATION_PARENT_INPUT="$(dirname -- "$DESTINATION_INPUT")"
DESTINATION_NAME="$(basename -- "$DESTINATION_INPUT")"
case "$DESTINATION_NAME" in
  ''|.|..) echo "backup destination must name a new child directory" >&2; exit 2 ;;
esac
if [ ! -d "$DESTINATION_PARENT_INPUT" ] || [ -L "$DESTINATION_PARENT_INPUT" ]; then
  echo "backup parent must be an existing, non-symlink directory: $DESTINATION_PARENT_INPUT" >&2
  exit 1
fi
DESTINATION_PARENT="$(CDPATH= cd -- "$DESTINATION_PARENT_INPUT" && pwd -P)"
DESTINATION="$DESTINATION_PARENT/$DESTINATION_NAME"
if paths_overlap "$DESTINATION" "$PACKAGE_INBOX"; then
  echo "backup destination must not overlap the package inbox: $DESTINATION" >&2
  exit 1
fi
if [ ! -f "$PACKAGE_DIR/deployment-lock.json" ] || [ -L "$PACKAGE_DIR/deployment-lock.json" ]; then
  echo "a regular, non-symlink deployment-lock.json is required before backup" >&2
  exit 1
fi
# Every recovery point is stamped with a package version, and that stamp is
# only meaningful if the database still matches the lock it comes from. A
# retried update reaches here with migrations already applied by the failed
# attempt; without this check the recovery point would label a new-schema dump
# with the old version, and restoring it would only fail at migrate.sh — after
# the production database was already dropped. The same drift makes a direct
# backup's VERSION stamp wrong, so compare the live ledger to the lock in both
# modes, before either branch chooses a stamp.
LEDGER_SNAPSHOT="$(mktemp "${TMPDIR:-/tmp}/openclaw-backup-ledger.XXXXXX")"
chmod 0600 "$LEDGER_SNAPSHOT"
{
  printf '%s\n' '\set ON_ERROR_STOP on'
  printf '%s\n' "SELECT (to_regclass('public.schema_migrations') IS NOT NULL) AS ledger_exists \\gset"
  printf '%s\n' '\if :ledger_exists'
  printf '%s\n' 'SELECT version,name,checksum_sha256 FROM schema_migrations ORDER BY version;'
  printf '%s\n' '\endif'
} | compose exec -T postgres \
  psql -X -w --quiet --username openclaw_owner --dbname openclaw \
  --tuples-only --no-align --field-separator="$(printf '\t')" \
  >"$LEDGER_SNAPSHOT"
python3 scripts/record_images.py --validate-applied-migrations \
  "$PACKAGE_DIR/deployment-lock.json" <"$LEDGER_SNAPSHOT" >/dev/null
if [ "$COMPATIBLE_BACKUP" -eq 1 ]; then
  python3 scripts/record_images.py --validate-live-structure \
    "$PACKAGE_DIR/deployment-lock.json"
  BACKUP_PACKAGE_VERSION="$(python3 scripts/record_images.py --lock-package-version \
    "$PACKAGE_DIR/deployment-lock.json")"
else
  python3 scripts/record_images.py --validate-live \
    "$PACKAGE_DIR/deployment-lock.json"
  BACKUP_PACKAGE_VERSION="$(tr -d '\r\n' < "$PACKAGE_DIR/VERSION")"
fi
if [ -e "$DESTINATION" ] || [ -L "$DESTINATION" ]; then
  echo "backup destination already exists; refusing to mix recovery points: $DESTINATION" >&2
  exit 1
fi
STAGING="$DESTINATION_PARENT/.${DESTINATION_NAME}.partial.$$"
if [ -e "$STAGING" ] || [ -L "$STAGING" ]; then
  echo "backup staging path already exists: $STAGING" >&2
  exit 1
fi
mkdir -m 0700 "$STAGING"

running_services="$(compose --profile tools ps --status running --services)"
if printf '%s\n' "$running_services" | grep -Fxq openclaw-gateway; then
  GATEWAY_WAS_RUNNING=1
fi

# Postgres remains available on its private local socket, but every state writer
# is stopped. This makes the SQLite/Task Flow/Lobster archive and the Postgres
# dump one named, quiesced recovery point.
compose --profile tools stop openclaw-cli openclaw-gateway >/dev/null
QUIESCED=1
compose exec -T postgres pg_isready --username openclaw_owner --dbname openclaw >/dev/null

compose exec -T postgres \
  pg_dump --username openclaw_owner --dbname openclaw --format=custom \
  >"$STAGING/postgres.dump"
compose --profile tools run --rm --no-deps --entrypoint tar openclaw-cli \
  -C /home/node/.openclaw --exclude=./openclaw.json \
  --exclude=./exec-approvals.json --exclude=./exec-approvals.sock -czf - . \
  >"$STAGING/openclaw-state.tar.gz"
compose --profile tools run --rm --no-deps --entrypoint tar openclaw-cli \
  -C /inbox -czf - . >"$STAGING/inbox-artifacts.tar.gz"
compose --profile tools run --rm --no-deps --entrypoint tar openclaw-cli \
  -C /quarantine -czf - . >"$STAGING/quarantine-artifacts.tar.gz"

# Not piped straight into tr: the pipeline's status would be tr's, so an
# unreachable database would read as an empty count and fail later as a
# data mismatch instead of here as the connection error it is.
unsafe_artifact_rows_raw="$(compose exec -T postgres psql -X -w \
  --username openclaw_owner --dbname openclaw --tuples-only --no-align \
  --set=ON_ERROR_STOP=1 \
  --command "SELECT count(*) FROM evidence_artifacts WHERE storage_tier IN ('workspace_file','quarantine') AND (storage_uri IS NULL OR storage_uri ~ E'[\\t\\r\\n]')")"
unsafe_artifact_rows="$(printf '%s' "$unsafe_artifact_rows_raw" | tr -d '[:space:]')"
if [ "$unsafe_artifact_rows" != "0" ]; then
  echo "database contains a local artifact URI that cannot be represented safely in recovery inventory" >&2
  exit 1
fi
tab="$(printf '\t')"
compose exec -T postgres psql -X -w --username openclaw_owner \
  --dbname openclaw --tuples-only --no-align --set=ON_ERROR_STOP=1 \
  --field-separator="$tab" \
  --command "SELECT sha256, storage_tier, storage_uri FROM evidence_artifacts WHERE storage_tier IN ('workspace_file','quarantine') ORDER BY id" \
  >"$STAGING/LOCAL_ARTIFACTS.tsv"

# Verify the bytes inside the just-created archives, not merely the live paths.
# Links/devices are forbidden so a URI cannot escape either staged root.
for archive_contract in \
  "state:openclaw-state.tar.gz" \
  "inbox:inbox-artifacts.tar.gz" \
  "quarantine:quarantine-artifacts.tar.gz"
do
  archive_label="${archive_contract%%:*}"
  archive_file="${archive_contract#*:}"
  case "$archive_label" in
    state) max_total="$STATE_ARCHIVE_MAX_BYTES" ;;
    inbox|quarantine) max_total=21474836480 ;;
    *) echo "unknown recovery archive class: $archive_label" >&2; exit 1 ;;
  esac
  python3 scripts/validate_recovery_archive.py \
    "$STAGING/$archive_file" "$STAGING/.verify-$archive_label" \
    --max-entries 100000 --max-member-bytes 2147483648 \
    --max-total-bytes "$max_total" --max-ratio 500 >/dev/null
done
verify_local_artifacts "$STAGING/LOCAL_ARTIFACTS.tsv" \
  "$STAGING/.verify-inbox" "$STAGING/.verify-quarantine" "$STAGING/.verify-state"
rm -rf "$STAGING/.verify-state" \
  "$STAGING/.verify-inbox" "$STAGING/.verify-quarantine"

printf '%s\n' "$BACKUP_PACKAGE_VERSION" >"$STAGING/VERSION"
cp "$PACKAGE_DIR/deployment-lock.json" "$STAGING/deployment-lock.json"

{
  echo "format_version=3"
  echo "created_utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "compose_project=$COMPOSE_PROJECT"
  echo "package_version=$BACKUP_PACKAGE_VERSION"
  echo "state_quiesced=true"
  echo "gateway_was_running=$GATEWAY_WAS_RUNNING"
  echo "generated_config_included=false"
  echo "exec_approvals_included=false"
  echo "local_artifact_inventory=LOCAL_ARTIFACTS.tsv"
  echo "state_archive_max_bytes=$STATE_ARCHIVE_MAX_BYTES"
} >"$STAGING/BACKUP_MANIFEST"

(
  cd "$STAGING"
  checksum_files="BACKUP_MANIFEST LOCAL_ARTIFACTS.tsv VERSION deployment-lock.json inbox-artifacts.tar.gz openclaw-state.tar.gz postgres.dump quarantine-artifacts.tar.gz"
  if command -v sha256sum >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    sha256sum $checksum_files >SHA256SUMS
  else
    # shellcheck disable=SC2086
    shasum -a 256 $checksum_files >SHA256SUMS
  fi
)
python3 scripts/authenticate_backup.py create "$ENV_FILE" \
  "$STAGING/SHA256SUMS" "$STAGING/BACKUP_AUTHENTICATION"

if [ "$GATEWAY_WAS_RUNNING" -eq 1 ] && [ "$LEAVE_QUIESCED" -ne 1 ]; then
  compose up -d --wait --no-deps openclaw-gateway >/dev/null
  compose exec -T openclaw-gateway \
    /workspaces/vc-chief/vc/bin/agent/vcops db-check >/dev/null
  QUIESCED=0
fi

# Publish the staged recovery point without ever overwriting an existing one.
# `mv -T -n` is GNU-only and this script otherwise tolerates BSD userland, so
# prefer a portable no-clobber rename: create the destination atomically with
# mkdir (which fails if it exists), then move the staged contents into it.
if [ -e "$DESTINATION" ]; then
  echo "backup destination already exists; refusing to overwrite it: $DESTINATION" >&2
  exit 1
fi
if ! mkdir "$DESTINATION"; then
  echo "backup destination appeared during publication; refusing to overwrite it" >&2
  exit 1
fi
# One rename, so the recovery point appears complete or not at all. A per-entry
# move loop is not atomic: an interrupt part-way through leaves a partial recovery
# point at the final path while the cleanup trap deletes the staging holding the
# rest. STAGING lives in DESTINATION_PARENT, so this is a same-filesystem rename.
#
# rename(2) directly, not `rmdir` + `mv`: POSIX rename replaces an existing
# EMPTY directory atomically and fails with ENOTEMPTY otherwise, so the mkdir
# reservation above is never released. Dropping it first would reopen the
# no-clobber hole this block exists to close — `mv` onto a directory that
# reappeared in the gap moves the staging INSIDE it and still reports success.
# `mv -T -n` has the same semantics but is GNU-only, and this script otherwise
# tolerates BSD userland.
python3 -c 'import os, sys; os.rename(sys.argv[1], sys.argv[2])' "$STAGING" "$DESTINATION"
STAGING=""
if [ "$LEAVE_QUIESCED" -eq 1 ]; then
  echo "Backup written atomically to $DESTINATION; state consumers remain stopped."
else
  echo "Backup written atomically to $DESTINATION."
fi
