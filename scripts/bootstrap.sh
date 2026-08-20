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
LOCK_DIR="/tmp/vc-lead-research-v3-lifecycle.lock"
LOCK_OWNED=0
LOCK_TOKEN=""
MUTATION_STARTED=0

compose() {
  docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" \
    --env-file "$ENV_FILE" "$@"
}

cleanup() {
  status="$?"
  trap - EXIT HUP INT QUIT TERM
  if [ "$status" -ne 0 ] && [ "$MUTATION_STARTED" -eq 1 ]; then
    compose --profile tools stop openclaw-cli openclaw-gateway >/dev/null 2>&1 || true
    # Worded for the whole window the flag guards, which opens at the runtime-role
    # rotation. Claiming a completed mutation would be wrong for a rotation that
    # refused before touching a service; saying nothing would be worse, since the
    # consumers are stopped either way and docs/RUNBOOK.md §9 is what tells the
    # operator how to get back.
    echo "Bootstrap failed at or after the runtime-role rotation; openclaw-gateway and openclaw-cli are stopped. Fix the reported cause and re-run ./scripts/bootstrap.sh (docs/RUNBOOK.md §9)." >&2
  fi
  if [ "$LOCK_OWNED" -eq 1 ]; then
    rm -f "$LOCK_DIR/owner"
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT QUIT TERM

cd "$PACKAGE_DIR"
./scripts/check_env.sh "$ENV_FILE"
python3 scripts/check_customization.py config/customization-profile.json "$ENV_FILE"
if ! mkdir "$LOCK_DIR"; then
  echo "another lifecycle operation is running or left a stale lock: $LOCK_DIR" >&2
  exit 1
fi
LOCK_OWNED=1
LOCK_TOKEN="bootstrap:$$"
printf '%s\n' "$LOCK_TOKEN" >"$LOCK_DIR/owner"

python3 scripts/render_channel_config.py "$ENV_FILE"
# Git carries only the executable bit, so a clone taken under a restrictive
# umask (this package's own scripts run at 077) leaves the host paths Compose
# bind-mounts unreadable to the service accounts inside the images: postgres
# runs as uid 999 and would skip an unreadable 000_roles.sh, silently starting
# a database with no runtime role. Normalize exactly the two bind-mounted paths
# and nothing else; the operator's umask still governs everything they own.
chmod a+rx "$PACKAGE_DIR/migrations/000_roles.sh"
chmod a+rx "$PACKAGE_DIR/inbox"
compose config --quiet
compose pull postgres
# Digest pulls (compose pull, BuildKit build bases) do not tag the pinned
# images in the local store; the deployment lock (record_images.py) inspects
# them by tag, so pull and tag each pinned image explicitly.
for image_variable in OPENCLAW_IMAGE POSTGRES_IMAGE; do
  pinned_image="$(grep "^${image_variable}=" "$ENV_FILE" | head -n 1 | cut -d= -f2-)"
  docker pull "$pinned_image"
  docker tag "$pinned_image" "${pinned_image%%@*}"
done
compose build --pull openclaw-gateway
# MUTATION_STARTED is armed BEFORE the rotation, never after it. The rotation is
# the mutating command -- it stops both consumers, force-recreates postgres,
# migrates, and recreates the gateway -- and `trap '...' HUP INT QUIT TERM` runs
# between commands, so a signal delivered while the rotation is running is
# handled with whatever value the flag had before it. Armed on the following
# line instead, a SIGTERM during the rotation left the gateway and CLI stopped
# by the rotation's own cleanup (which prints nothing) while this script's
# cleanup skipped its branch entirely: measured, the operator got "Terminated"
# and no statement at all that the deployment was down. The same window also
# covers the one-line gap after a *successful* rotation, where a signal would
# leave a gateway serving traffic from a bootstrap that never reached
# record_images.py.
#
# A crash-left rotation lock is a state docs/OPERATIONS.md documents as an
# expected leftover ("can outlive an interrupted bootstrap or update"), but
# rotate_runtime_role.sh only discovers it below -- after MUTATION_STARTED has
# armed the handler that leaves consumers stopped. Measured under dash: without
# this check, a lock left by an earlier crash made a refusal that had touched
# nothing print "openclaw-gateway and openclaw-cli are stopped" and run the
# cleanup's compose stop against a healthy deployment. Mirror the check here,
# while production is still running, exactly as update.sh does;
# docs/MAINTAINING.md instructs re-running this script on an
# already-bootstrapped deployment, so this is a live path and not
# first-install-only. The lifecycle-lock check above
# does not cover it: an operator who cleared only that lock lands here.
ROTATION_LOCK_DIR="/tmp/vc-lead-research-v3-rotation.lock"
# The remedy pointer below names 'First install', not 'Secrets'. The whole
# stale-lock recovery procedure -- confirm no rotation process is active, then
# remove the directory with `rm -rf` because it is not empty (it holds
# deployment.env, a verbatim copy of .env) -- sits in the rotate_runtime_role.sh
# paragraph under `## First install`. If the paragraph moves, move this citation
# with it.
if [ -e "$ROTATION_LOCK_DIR" ]; then
  echo "a database-secret rotation is running or left a stale lock: $ROTATION_LOCK_DIR" >&2
  echo "resolve it before bootstrapping; nothing has been changed. docs/OPERATIONS.md," >&2
  echo "'First install', documents the crash-left case: confirm no rotation is" >&2
  echo "active, then remove the whole directory ('rm -rf', not 'rmdir')." >&2
  exit 1
fi

# Arming here does mean a pre-mutation refusal inside rotate_runtime_role.sh
# also runs the cleanup below, stopping both consumers for a refusal that
# changed nothing. This script has already run every validation step the
# rotation repeats (check_env.sh, check_customization.py,
# render_channel_config.py, compose config) above, and the one crash state
# docs/OPERATIONS.md documents as an expected leftover -- a stale rotation lock
# -- is refused by the mirror immediately above, while production is still
# running. What can still refuse in this window is losing the race for that lock
# between the mirror and the rotation's own `mkdir`, and the rotation's private
# .env snapshot. Neither can be checked any earlier, and both are genuinely
# rare. The cleanup message is worded for both cases rather than claiming a
# mutation that may not have happened.
MUTATION_STARTED=1
OPENCLAW_LIFECYCLE_LOCK_TOKEN="$LOCK_TOKEN" ./scripts/rotate_runtime_role.sh
# vcops emits its envelope -- success and failure alike -- on stdout, so
# >/dev/null discarded the only description of a failed database check.
if ! DB_CHECK_REPORT="$(compose exec -T openclaw-gateway \
  /workspaces/vc-chief/vc/bin/agent/vcops db-check)"; then
  printf '%s\n' "$DB_CHECK_REPORT" >&2
  echo "database check failed after reconciliation." >&2
  exit 1
fi
python3 scripts/record_images.py
compose ps
MUTATION_STARTED=0

echo "Bootstrap completed. Keep PRIMARY_CHANNEL=none until the selected live acceptance matrix is ready to run."
