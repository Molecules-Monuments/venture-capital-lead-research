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
    echo "Bootstrap failed after service mutation; state consumers remain stopped." >&2
  fi
  if [ "$LOCK_OWNED" -eq 1 ]; then
    rm -f "$LOCK_DIR/owner"
    rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT
trap 'exit 1' HUP INT TERM

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
MUTATION_STARTED=1
OPENCLAW_LIFECYCLE_LOCK_TOKEN="$LOCK_TOKEN" ./scripts/rotate_runtime_role.sh
compose exec -T openclaw-gateway \
  /workspaces/vc-chief/vc/bin/agent/vcops db-check >/dev/null
python3 scripts/record_images.py
compose ps
MUTATION_STARTED=0

echo "Bootstrap completed. Keep PRIMARY_CHANNEL=none until the selected live acceptance matrix is ready to run."
