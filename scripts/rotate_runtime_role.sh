#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
set -eu
umask 077
# Keep lifecycle runs from shedding bytecode caches into the pristine package.
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="$PACKAGE_DIR/.env"
COMPOSE_FILE="$PACKAGE_DIR/docker-compose.yml"
COMPOSE_PROJECT="vc-lead-research-v3"
LIFECYCLE_LOCK_DIR="/tmp/vc-lead-research-v3-lifecycle.lock"
LIFECYCLE_LOCK_OWNED=0
LIFECYCLE_LOCK_TOKEN=""
cd "$PACKAGE_DIR"

if [ ! -f "$ENV_FILE" ] || [ -L "$ENV_FILE" ]; then
  echo ".env must be a regular, non-symlink file" >&2
  exit 1
fi

LOCK_DIR="/tmp/vc-lead-research-v3-rotation.lock"
ENV_SNAPSHOT="$LOCK_DIR/deployment.env"
ROTATION_LOCK_OWNED=0
ROTATION_STARTED=0
compose() {
  docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" \
    --env-file "$ENV_SNAPSHOT" "$@"
}
cleanup() {
  status="$?"
  # Traps reset first, as in every sibling script: a second interrupt during
  # the compose stop below would otherwise re-enter this handler and abandon
  # the locks it exists to release.
  trap - EXIT HUP INT QUIT TERM
  # Only a lock this run actually acquired is this run's to release — the
  # snapshot and lock directory belong to whoever holds them.
  if [ "$ROTATION_LOCK_OWNED" -eq 1 ]; then
    if [ "$status" -ne 0 ] && [ "$ROTATION_STARTED" -eq 1 ] && [ -f "$ENV_SNAPSHOT" ]; then
      compose --profile tools stop openclaw-cli openclaw-gateway >/dev/null 2>&1 || true
    fi
    rm -f "$ENV_SNAPSHOT"
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
  if [ "$LIFECYCLE_LOCK_OWNED" -eq 1 ]; then
    rm -f "$LIFECYCLE_LOCK_DIR/owner"
    rmdir "$LIFECYCLE_LOCK_DIR" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
# Armed before either lock is taken: an interrupt in the window between
# acquiring a lock and installing the handler would otherwise leak it.
trap cleanup EXIT
trap 'exit 1' HUP INT QUIT TERM

if [ -n "${OPENCLAW_LIFECYCLE_LOCK_TOKEN:-}" ]; then
  if [ ! -f "$LIFECYCLE_LOCK_DIR/owner" ] || \
     [ -L "$LIFECYCLE_LOCK_DIR/owner" ] || \
     [ "$(cat "$LIFECYCLE_LOCK_DIR/owner")" != "$OPENCLAW_LIFECYCLE_LOCK_TOKEN" ]; then
    echo "invalid inherited lifecycle lock token" >&2
    exit 1
  fi
else
  if ! mkdir "$LIFECYCLE_LOCK_DIR"; then
    echo "another lifecycle operation is running or left a stale lock: $LIFECYCLE_LOCK_DIR" >&2
    exit 1
  fi
  LIFECYCLE_LOCK_OWNED=1
  LIFECYCLE_LOCK_TOKEN="rotate:$$"
  printf '%s\n' "$LIFECYCLE_LOCK_TOKEN" >"$LIFECYCLE_LOCK_DIR/owner"
fi

if ! (umask 077 && mkdir "$LOCK_DIR"); then
  echo "another database-secret rotation is running or left a stale lock: $LOCK_DIR" >&2
  exit 1
fi
ROTATION_LOCK_OWNED=1
cp "$ENV_FILE" "$ENV_SNAPSHOT"
chmod 0600 "$ENV_SNAPSHOT"

./scripts/check_env.sh "$ENV_SNAPSHOT"
# Validate the reviewed profile<->environment binding before rendering: this is
# the render+recreate step the RUNBOOK's channel-activation path runs, so a
# channel/model/score-band change that skipped the profile fails closed here.
python3 scripts/check_customization.py config/customization-profile.json "$ENV_SNAPSHOT"
# The renderer's lifecycle guard only accepts the package .env; this snapshot
# is a same-content private copy taken above, so authorize it explicitly.
OPENCLAW_RENDER_ALLOW_SNAPSHOT=1 python3 scripts/render_channel_config.py "$ENV_SNAPSHOT"
compose config --quiet

# Compose does not include environment-sourced secret contents in its service
# configuration hash. Stop every consumer and force recreation so both current
# secrets are mounted before the database roles are changed.
ROTATION_STARTED=1
compose --profile tools stop openclaw-cli openclaw-gateway
compose up -d --wait --force-recreate postgres

# The role initializer is also the password/restriction reconciler. It proves
# TCP authentication with both newly mounted credentials before returning.
compose exec -T -e OPENCLAW_VERIFY_TCP_AUTH=1 postgres \
  /docker-entrypoint-initdb.d/000_roles.sh

# Kept out of a pipeline so psql's own failure status survives: piped into tr,
# an unreachable database would yield "" and be reported as a failed role
# reconciliation rather than a connection error.
restricted_raw="$(compose exec -T postgres \
  psql -X -w --username openclaw_owner --dbname openclaw --tuples-only --no-align \
  --set=ON_ERROR_STOP=1 \
  --command "SELECT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole AND NOT rolinherit AND NOT rolreplication AND NOT rolbypassrls AND rolconnlimit = 32 AND (rolvaliduntil IS NULL OR rolvaliduntil = 'infinity'::timestamptz) AND NOT EXISTS (SELECT 1 FROM pg_auth_members AS membership WHERE membership.member = pg_roles.oid OR membership.roleid = pg_roles.oid) FROM pg_roles WHERE rolname='openclaw_runtime'")"
restricted="$(printf '%s' "$restricted_raw" | tr -d '[:space:]')"

if [ "$restricted" != "t" ]; then
  echo "openclaw_runtime role restrictions did not reconcile" >&2
  exit 1
fi

./scripts/migrate.sh "$ENV_SNAPSHOT"

# Recreate the optional CLI container as stopped and the gateway as running so
# no existing consumer can retain a stale environment-backed secret mount.
compose run --rm --no-deps openclaw-state-init
compose --profile tools up --force-recreate --no-deps --no-start openclaw-cli
compose up -d --wait --force-recreate --no-deps openclaw-gateway
compose exec -T openclaw-gateway \
  /workspaces/vc-chief/vc/bin/agent/vcops db-check
compose --profile tools run --rm --no-deps \
  --entrypoint /workspaces/vc-chief/vc/bin/agent/vcops openclaw-cli db-check

echo "Owner/runtime database passwords, runtime restrictions, and secret consumers reconciled."
