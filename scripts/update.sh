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
BACKUP_DESTINATION="${1:-}"
LOCK_OWNED=0
LOCK_TOKEN=""
MUTATION_STARTED=0

compose() {
  docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" \
    --env-file "$ENV_FILE" "$@"
}

cleanup() {
  status="$?"
  trap - EXIT HUP INT TERM
  if [ "$status" -ne 0 ] && [ "$MUTATION_STARTED" -eq 1 ]; then
    compose --profile tools stop openclaw-cli openclaw-gateway >/dev/null 2>&1 || true
    echo "Update or pre-update backup failed after lifecycle mutation began; consumers remain stopped. Repair the release, or restore the verified pre-update backup if its final directory was published, before restarting traffic." >&2
  fi
  if [ "$LOCK_OWNED" -eq 1 ]; then
    rm -f "$LOCK_DIR/owner"
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

if [ -z "$BACKUP_DESTINATION" ]; then
  echo "usage: $0 NEW_PRE_UPDATE_BACKUP_DIRECTORY" >&2
  exit 2
fi

cd "$PACKAGE_DIR"
./scripts/check_env.sh "$ENV_FILE"
# Enforce the reviewed customization profile <-> environment binding on the
# update path too, not only in bootstrap: an operator who changed a channel,
# model tier, or score band in .env without updating the profile fails closed
# here instead of deploying a config whose reviewed binding was never validated.
python3 scripts/check_customization.py config/customization-profile.json "$ENV_FILE"
if ! mkdir "$LOCK_DIR"; then
  echo "another lifecycle operation is running or left a stale lock: $LOCK_DIR" >&2
  exit 1
fi
LOCK_OWNED=1
LOCK_TOKEN="update:$$"
printf '%s\n' "$LOCK_TOKEN" >"$LOCK_DIR/owner"

# Reject trivially invalid backup destinations before any consumer is touched:
# these mirror backup.sh's own early checks so a typo'd path fails here while
# the production gateway is still running, not after the quiesce handler has
# already stopped it.
case "$BACKUP_DESTINATION" in
  /*) ;;
  *) BACKUP_DESTINATION="$PWD/$BACKUP_DESTINATION" ;;
esac
DESTINATION_PARENT_INPUT="$(dirname -- "$BACKUP_DESTINATION")"
DESTINATION_NAME="$(basename -- "$BACKUP_DESTINATION")"
case "$DESTINATION_NAME" in
  ''|.|..) echo "backup destination must name a new child directory" >&2; exit 2 ;;
esac
if [ ! -d "$DESTINATION_PARENT_INPUT" ] || [ -L "$DESTINATION_PARENT_INPUT" ]; then
  echo "backup parent must be an existing, non-symlink directory: $DESTINATION_PARENT_INPUT" >&2
  exit 1
fi
if [ ! -w "$DESTINATION_PARENT_INPUT" ]; then
  echo "backup parent must be writable: $DESTINATION_PARENT_INPUT" >&2
  exit 1
fi
if [ -e "$BACKUP_DESTINATION" ] || [ -L "$BACKUP_DESTINATION" ]; then
  echo "backup destination already exists: $BACKUP_DESTINATION" >&2
  exit 1
fi
if [ ! -f "$PACKAGE_DIR/deployment-lock.json" ] || [ -L "$PACKAGE_DIR/deployment-lock.json" ]; then
  echo "a regular, non-symlink deployment-lock.json is required before update" >&2
  exit 1
fi
# The update-mode backup validates the lock's structure before quiescing;
# mirror it here so a malformed lock fails while the gateway is still running.
python3 scripts/record_images.py --validate-live-structure \
  "$PACKAGE_DIR/deployment-lock.json" >/dev/null || {
  echo "deployment-lock.json failed structural validation" >&2
  exit 1
}
if [ ! -d "$PACKAGE_DIR/inbox" ] || [ -L "$PACKAGE_DIR/inbox" ]; then
  echo "package inbox must be an existing, non-symlink directory" >&2
  exit 1
fi
PACKAGE_INBOX="$(CDPATH= cd -- "$PACKAGE_DIR/inbox" && pwd -P)"
DESTINATION_PARENT="$(CDPATH= cd -- "$DESTINATION_PARENT_INPUT" && pwd -P)"
case "$DESTINATION_PARENT/$DESTINATION_NAME" in
  "$PACKAGE_INBOX"|"$PACKAGE_INBOX"/*)
    echo "backup destination must not overlap the package inbox" >&2
    exit 1 ;;
esac

# Hold one lifecycle lock from the quiesced old-state recovery point through the
# new image/schema health checks. A failed update never restarts a mixed system.
MUTATION_STARTED=1
OPENCLAW_LIFECYCLE_LOCK_TOKEN="$LOCK_TOKEN" OPENCLAW_BACKUP_LEAVE_QUIESCED=1 \
  OPENCLAW_BACKUP_COMPATIBLE_LOCK=1 \
  ./scripts/backup.sh "$BACKUP_DESTINATION"
python3 scripts/render_channel_config.py "$ENV_FILE"
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
OPENCLAW_LIFECYCLE_LOCK_TOKEN="$LOCK_TOKEN" ./scripts/rotate_runtime_role.sh
compose exec -T openclaw-gateway \
  /workspaces/vc-chief/vc/bin/agent/vcops db-check >/dev/null
python3 scripts/record_images.py
compose ps
MUTATION_STARTED=0

echo "Update completed from a quiesced pre-update recovery point. Re-run every affected G8 live gate before enabling traffic."
