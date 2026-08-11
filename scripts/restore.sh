#!/bin/sh
# SPDX-License-Identifier: 0BSD
set -eu
umask 077
# Keep lifecycle runs from shedding bytecode caches into the pristine package.
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="$PACKAGE_DIR/.env"
COMPOSE_FILE="$PACKAGE_DIR/docker-compose.yml"
COMPOSE_PROJECT="openclaw-lead-research-v3"
LOCK_DIR="/tmp/openclaw-lead-research-v3-lifecycle.lock"
# The state archive bound is operator-tunable because intake snapshots
# accumulate in that tier; check_env.py validates the range.
STATE_ARCHIVE_MAX_BYTES="$(sed -n 's/^OPENCLAW_STATE_ARCHIVE_MAX_BYTES=//p' "$ENV_FILE" 2>/dev/null | head -n 1)"
[ -n "$STATE_ARCHIVE_MAX_BYTES" ] || STATE_ARCHIVE_MAX_BYTES=2147483648
BACKUP_INPUT="${1:-}"
CONFIRM="${2:-}"
VALIDATION_DIR=""
VALIDATION_DB=""
LOCK_OWNED=0
LOCK_TOKEN=""
MUTATION_STARTED=0

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

cleanup() {
  status="$?"
  trap - EXIT HUP INT TERM
  if [ -n "$VALIDATION_DB" ]; then
    compose exec -T postgres dropdb --username openclaw_owner --if-exists \
      --force "$VALIDATION_DB" >/dev/null 2>&1 || true
  fi
  if [ "$status" -ne 0 ] && [ "$MUTATION_STARTED" -eq 1 ]; then
    compose --profile tools stop openclaw-cli openclaw-gateway >/dev/null 2>&1 || true
    echo "Restore failed after mutation began; consumers remain stopped. Repair or retry from the verified recovery point before starting traffic." >&2
  fi
  if [ -n "$VALIDATION_DIR" ] && [ -d "$VALIDATION_DIR" ]; then
    rm -rf -- "$VALIDATION_DIR"
  fi
  if [ "$LOCK_OWNED" -eq 1 ]; then
    rm -f "$LOCK_DIR/owner"
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

fail() {
  echo "$*" >&2
  exit 1
}

verify_checksums() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -c SHA256SUMS
  else
    shasum -a 256 -c SHA256SUMS
  fi
}

sha256_path() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

write_db_artifact_inventory() {
  database="$1"
  output="$2"
  # Kept out of a pipeline so psql's own failure status survives; see backup.sh.
  unsafe_rows_raw="$(compose exec -T postgres psql -X -w \
    --username openclaw_owner --dbname "$database" --tuples-only --no-align \
    --set=ON_ERROR_STOP=1 \
    --command "SELECT count(*) FROM evidence_artifacts WHERE storage_tier IN ('workspace_file','quarantine') AND (storage_uri IS NULL OR storage_uri ~ E'[\\t\\r\\n]')")"
  unsafe_rows="$(printf '%s' "$unsafe_rows_raw" | tr -d '[:space:]')"
  [ "$unsafe_rows" = "0" ] || fail "database contains an unsafe local artifact URI"
  tab="$(printf '\t')"
  compose exec -T postgres psql -X -w --username openclaw_owner \
    --dbname "$database" --tuples-only --no-align --set=ON_ERROR_STOP=1 \
    --field-separator="$tab" \
    --command "SELECT sha256, storage_tier, storage_uri FROM evidence_artifacts WHERE storage_tier IN ('workspace_file','quarantine') ORDER BY id" \
    >"$output"
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
    [ -z "${extra:-}" ] || fail "malformed local-artifact inventory"
    case "$digest" in
      *[!0-9a-f]*|'') fail "invalid artifact digest in recovery inventory" ;;
    esac
    [ "${#digest}" -eq 64 ] || fail "invalid artifact digest length"
    case "$tier:$uri" in
      workspace_file:state://*) root="$state_root/vcops"; relative="${uri#state://}" ;;
      workspace_file:inbox://*) root="$inbox_root"; relative="${uri#inbox://}" ;;
      workspace_file:/inbox/*) root="$inbox_root"; relative="${uri#/inbox/}" ;;
      quarantine:quarantine://*) root="$quarantine_root"; relative="${uri#quarantine://}" ;;
      quarantine:/quarantine/*) root="$quarantine_root"; relative="${uri#/quarantine/}" ;;
      *) fail "unsupported local artifact URI in database: $tier:$uri" ;;
    esac
    case "$relative" in
      ''|/*|..|../*|*/..|*/../*) fail "unsafe local artifact URI: $uri" ;;
    esac
    artifact_path="$root/$relative"
    if [ ! -f "$artifact_path" ] || [ -L "$artifact_path" ]; then
      fail "database artifact URI does not resolve to a regular recovery file: $uri"
    fi
    actual="$(sha256_path "$artifact_path")"
    [ "$actual" = "$digest" ] || fail "database artifact hash does not match recovery file: $uri"
  done <"$inventory"
}

validate_checksum_manifest() {
  seen_required=""
  while IFS=' ' read -r digest member extra; do
    case "$member" in
      \**) member="${member#\*}" ;;
    esac
    if [ -n "${extra:-}" ] || [ "${#digest}" -ne 64 ]; then
      fail "malformed SHA256SUMS entry"
    fi
    case "$digest" in
      *[!0-9a-f]*) fail "malformed SHA256SUMS digest" ;;
    esac
    case "$member" in
      BACKUP_MANIFEST|LOCAL_ARTIFACTS.tsv|VERSION|inbox-artifacts.tar.gz|openclaw-state.tar.gz|postgres.dump|quarantine-artifacts.tar.gz|deployment-lock.json) ;;
      *) fail "unexpected path in SHA256SUMS: $member" ;;
    esac
    case " $seen_required " in
      *" $member "*) fail "duplicate SHA256SUMS entry: $member" ;;
    esac
    seen_required="$seen_required $member"
  done <"$VALIDATION_DIR/SHA256SUMS"
  for required_member in BACKUP_MANIFEST LOCAL_ARTIFACTS.tsv VERSION deployment-lock.json inbox-artifacts.tar.gz openclaw-state.tar.gz postgres.dump quarantine-artifacts.tar.gz; do
    case " $seen_required " in
      *" $required_member "*) ;;
      *) fail "missing SHA256SUMS entry: $required_member" ;;
    esac
  done
}

validate_archive() {
  archive="$1"
  label="$2"
  list_file="$VALIDATION_DIR/$label.list"
  case "$label" in
    state|active-state) max_total="$STATE_ARCHIVE_MAX_BYTES" ;;
    inbox|quarantine|active-quarantine) max_total=21474836480 ;;
    *) fail "unknown recovery archive class: $label" ;;
  esac
  python3 scripts/validate_recovery_archive.py \
    "$archive" "$VALIDATION_DIR/$label" --list-file "$list_file" \
    --max-entries 100000 --max-member-bytes 2147483648 \
    --max-total-bytes "$max_total" --max-ratio 500 >/dev/null
}

restore_host_tree() {
  source_dir="$1"
  target_dir="$2"
  find "$target_dir" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  (cd "$source_dir" && tar -cf - .) | (cd "$target_dir" && tar -xf -)
  # Staging extraction ran under umask 077, which would leave the restored
  # inbox originals unreadable to the unprivileged container user that mounts
  # them. Match the documented contract: read-only originals, readable through
  # the bind mount; host confidentiality comes from the package directory.
  find "$target_dir" -type d -exec chmod 0755 {} +
  find "$target_dir" -type f -exec chmod 0444 {} +
}

stage_backup() {
  # Copy every backup member into private staging with a single read of each,
  # BEFORE any verification. Authenticity (HMAC) and checksums are then proven
  # against the staged bytes only, and every later step — validation and the
  # destructive production restore alike — reads exclusively from staging. The
  # operator-writable backup directory is never re-read after this point, so
  # the bytes that were authenticated are exactly the bytes that get restored
  # (no verify-then-reread window).
  for member in $required_files; do
    cp -- "$BACKUP_DIR/$member" "$VALIDATION_DIR/$member" || \
      fail "failed to stage backup member: $member"
    if [ -L "$VALIDATION_DIR/$member" ] || [ ! -f "$VALIDATION_DIR/$member" ]; then
      fail "staged backup member must be a regular file: $member"
    fi
  done
}

if [ -z "$BACKUP_INPUT" ] || [ "$CONFIRM" != "--confirm-destructive-restore" ]; then
  echo "usage: $0 BACKUP_DIRECTORY --confirm-destructive-restore" >&2
  exit 2
fi

case "$BACKUP_INPUT" in
  /*) ;;
  *) BACKUP_INPUT="$PWD/$BACKUP_INPUT" ;;
esac
if [ ! -d "$BACKUP_INPUT" ] || [ -L "$BACKUP_INPUT" ]; then
  fail "backup must be an existing, non-symlink directory: $BACKUP_INPUT"
fi
BACKUP_DIR="$(CDPATH= cd -- "$BACKUP_INPUT" && pwd -P)"

if [ ! -d "$PACKAGE_DIR/inbox" ] || [ -L "$PACKAGE_DIR/inbox" ]; then
  fail "package inbox must be an existing, non-symlink directory"
fi
PACKAGE_INBOX="$(CDPATH= cd -- "$PACKAGE_DIR/inbox" && pwd -P)"
if paths_overlap "$BACKUP_DIR" "$PACKAGE_INBOX"; then
  fail "backup source must not overlap the package inbox: $BACKUP_DIR"
fi

cd "$PACKAGE_DIR"
./scripts/check_env.sh "$ENV_FILE" >/dev/null
# The restore target must satisfy the reviewed profile<->environment binding
# before its rendered config is used to bring the deployment back up.
python3 scripts/check_customization.py config/customization-profile.json "$ENV_FILE"
if ! mkdir "$LOCK_DIR"; then
  fail "another lifecycle operation is running or left a stale lock: $LOCK_DIR"
fi
LOCK_OWNED=1
LOCK_TOKEN="restore:$$"
printf '%s\n' "$LOCK_TOKEN" >"$LOCK_DIR/owner"

required_files="BACKUP_AUTHENTICATION BACKUP_MANIFEST LOCAL_ARTIFACTS.tsv SHA256SUMS VERSION deployment-lock.json inbox-artifacts.tar.gz openclaw-state.tar.gz postgres.dump quarantine-artifacts.tar.gz"
for required_file in $required_files; do
  if [ ! -f "$BACKUP_DIR/$required_file" ] || [ -L "$BACKUP_DIR/$required_file" ]; then
    fail "backup member must be a regular, non-symlink file: $required_file"
  fi
done
if [ ! -f "$PACKAGE_DIR/deployment-lock.json" ] || [ -L "$PACKAGE_DIR/deployment-lock.json" ]; then
  fail "the restore package needs its locally recorded deployment-lock.json"
fi

# Stage the whole backup into private staging first, then authenticate and
# checksum-verify the staged bytes. All validation and the destructive restore
# below consume only the staged tree.
VALIDATION_DIR="$(mktemp -d "${TMPDIR:-/tmp}/openclaw-restore-validation.XXXXXX")"
VALIDATION_DIR="$(CDPATH= cd -- "$VALIDATION_DIR" && pwd -P)"
if paths_overlap "$VALIDATION_DIR" "$PACKAGE_INBOX"; then
  fail "restore validation staging must not overlap the package inbox: $VALIDATION_DIR"
fi
stage_backup
python3 scripts/authenticate_backup.py verify "$ENV_FILE" \
  "$VALIDATION_DIR/SHA256SUMS" "$VALIDATION_DIR/BACKUP_AUTHENTICATION" >/dev/null || \
  fail "backup authenticity verification failed"
validate_checksum_manifest
(
  cd "$VALIDATION_DIR"
  verify_checksums
)

grep -Fxq 'format_version=3' "$VALIDATION_DIR/BACKUP_MANIFEST" || \
  fail "unsupported backup format"
grep -Fxq 'state_quiesced=true' "$VALIDATION_DIR/BACKUP_MANIFEST" || \
  fail "backup does not attest quiesced state"
# BACKUP_MANIFEST records the bound in force when the recovery point was
# written, not the archive's validated total, so the recorded bound is the only
# pre-mutation proxy for "could this archive have needed more than this host
# allows". Reject a smaller target bound conservatively — the archive may in
# fact be far below it — naming the variable and the required minimum, rather
# than risking a byte-limit abort inside archive validation that names neither,
# or one during the post-mutation active-state re-validation below, after the
# deployment has already been replaced. Manifests written before this field
# existed (same format_version=3) omit the line and fall through to today's
# behavior.
BACKUP_STATE_BOUND="$(sed -n 's/^state_archive_max_bytes=//p' "$VALIDATION_DIR/BACKUP_MANIFEST" | head -n 1)"
if [ -n "$BACKUP_STATE_BOUND" ]; then
  case "$BACKUP_STATE_BOUND" in
    *[!0-9]*) fail "backup manifest carries a malformed state_archive_max_bytes: $BACKUP_STATE_BOUND" ;;
  esac
  if [ "$BACKUP_STATE_BOUND" -gt "$STATE_ARCHIVE_MAX_BYTES" ]; then
    fail "backup was written with OPENCLAW_STATE_ARCHIVE_MAX_BYTES=$BACKUP_STATE_BOUND but this host's effective bound is $STATE_ARCHIVE_MAX_BYTES; set OPENCLAW_STATE_ARCHIVE_MAX_BYTES in .env to at least $BACKUP_STATE_BOUND and re-run"
  fi
fi
if [ "$(tr -d '\r\n' < "$VALIDATION_DIR/VERSION")" != "$(tr -d '\r\n' < "$PACKAGE_DIR/VERSION")" ]; then
  fail "backup package version differs from this restore package; use the matching reviewed release"
fi
python3 scripts/record_images.py --validate-live "$PACKAGE_DIR/deployment-lock.json" >/dev/null || \
  fail "current deployment lock or live image IDs do not match this exact release"
python3 scripts/record_images.py --validate-lock "$VALIDATION_DIR/deployment-lock.json" >/dev/null || \
  fail "backup deployment lock does not match this exact release"

# Validate every stream completely and extract into private staging before any
# production database, volume, inbox, or quarantine content is changed. Each
# staged archive is removed right after extraction to bound peak staging space.
validate_archive "$VALIDATION_DIR/openclaw-state.tar.gz" state
rm -f -- "$VALIDATION_DIR/openclaw-state.tar.gz"
if grep -Eq '^(openclaw\.json|exec-approvals\.(json|sock))$' "$VALIDATION_DIR/state.list"; then
  fail "state archive contains generated runtime config or exec approvals"
fi
validate_archive "$VALIDATION_DIR/inbox-artifacts.tar.gz" inbox
rm -f -- "$VALIDATION_DIR/inbox-artifacts.tar.gz"
validate_archive "$VALIDATION_DIR/quarantine-artifacts.tar.gz" quarantine
rm -f -- "$VALIDATION_DIR/quarantine-artifacts.tar.gz"
verify_local_artifacts "$VALIDATION_DIR/LOCAL_ARTIFACTS.tsv" \
  "$VALIDATION_DIR/inbox" "$VALIDATION_DIR/quarantine" "$VALIDATION_DIR/state"
python3 scripts/render_channel_config.py "$ENV_FILE" >/dev/null
compose config --quiet
compose exec -T postgres pg_restore --list \
  <"$VALIDATION_DIR/postgres.dump" >"$VALIDATION_DIR/postgres.list"

# Prove the logical dump can be restored into a disposable database before the
# production database is dropped. This is validation, not a release acceptance
# substitute for the isolated-host G8 recovery drill.
VALIDATION_DB="openclaw_restore_validate_$$"
compose exec -T postgres createdb --username openclaw_owner "$VALIDATION_DB"
compose exec -T postgres pg_restore --username openclaw_owner \
  --dbname "$VALIDATION_DB" --exit-on-error --no-owner --no-privileges \
  <"$VALIDATION_DIR/postgres.dump"
write_db_artifact_inventory "$VALIDATION_DB" "$VALIDATION_DIR/database-artifacts.tsv"
cmp "$VALIDATION_DIR/LOCAL_ARTIFACTS.tsv" "$VALIDATION_DIR/database-artifacts.tsv" >/dev/null || \
  fail "database local-artifact inventory does not match the recovery archives"
compose exec -T postgres dropdb --username openclaw_owner --force "$VALIDATION_DB"
VALIDATION_DB=""

MUTATION_STARTED=1
compose --profile tools stop openclaw-cli openclaw-gateway >/dev/null

compose exec -T postgres dropdb --username openclaw_owner --if-exists \
  --force openclaw
compose exec -T postgres createdb --username openclaw_owner openclaw
compose exec -T postgres pg_restore --username openclaw_owner \
  --dbname openclaw --exit-on-error <"$VALIDATION_DIR/postgres.dump"
# pg_dump without --create never emits database-level (pg_database) ACLs, and
# the restored schema_migrations ledger already records 002, so migrate.sh
# below treats that migration as applied and never reapplies it. Re-execute its
# idempotent database-level hardening so PUBLIC does not silently regain
# TEMPORARY on the restored database.
compose exec -T postgres psql -X -w --username openclaw_owner \
  --dbname openclaw --set=ON_ERROR_STOP=1 \
  --command "REVOKE TEMPORARY ON DATABASE openclaw FROM PUBLIC" \
  --command "REVOKE CREATE ON DATABASE openclaw FROM PUBLIC" \
  --command "GRANT CONNECT ON DATABASE openclaw TO openclaw_runtime"

(cd "$VALIDATION_DIR/state" && tar -cf - .) | \
  compose --profile tools run --rm --no-deps --entrypoint sh openclaw-cli -c \
    'set -eu; find /home/node/.openclaw -mindepth 1 -maxdepth 1 ! -name exec-approvals.json -exec rm -rf -- {} +; tar -C /home/node/.openclaw -xf -'
restore_host_tree "$VALIDATION_DIR/inbox" "$PACKAGE_DIR/inbox"
(cd "$VALIDATION_DIR/quarantine" && tar -cf - .) | \
  compose --profile tools run --rm --no-deps --entrypoint sh openclaw-cli -c \
    'set -eu; find /quarantine -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +; tar -C /quarantine -xf -'

# Read all three artifact roots back from where the restore actually put them.
# Hashing the archive's own copy of the state tree would compare the archive
# against itself and prove nothing about the restored deployment, unlike the
# inbox and quarantine lanes beside it.
compose --profile tools run --rm --no-deps --entrypoint tar openclaw-cli \
  -C /quarantine -czf - . >"$VALIDATION_DIR/active-quarantine.tar.gz"
validate_archive "$VALIDATION_DIR/active-quarantine.tar.gz" active-quarantine
compose --profile tools run --rm --no-deps --entrypoint tar openclaw-cli \
  -C /home/node/.openclaw -czf - . >"$VALIDATION_DIR/active-state.tar.gz"
validate_archive "$VALIDATION_DIR/active-state.tar.gz" active-state
verify_local_artifacts "$VALIDATION_DIR/LOCAL_ARTIFACTS.tsv" \
  "$PACKAGE_DIR/inbox" "$VALIDATION_DIR/active-quarantine" "$VALIDATION_DIR/active-state"

./scripts/migrate.sh "$ENV_FILE"
compose exec -T -e OPENCLAW_VERIFY_TCP_AUTH=1 postgres \
  /docker-entrypoint-initdb.d/000_roles.sh
compose run --rm --no-deps openclaw-state-init
compose --profile tools up --force-recreate --no-deps --no-start openclaw-cli
compose up -d --wait --force-recreate --no-deps openclaw-gateway
compose exec -T openclaw-gateway \
  /workspaces/vc-chief/vc/bin/agent/vcops db-check
compose --profile tools run --rm --no-deps \
  --entrypoint /workspaces/vc-chief/vc/bin/agent/vcops openclaw-cli db-check
compose ps

MUTATION_STARTED=0
echo "Restore completed from the staged, checksum-verified recovery point. G8 doctor, Task Flow audit, Lobster resume, and channel/model checks remain mandatory on this target."
