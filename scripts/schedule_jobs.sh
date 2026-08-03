#!/bin/sh
# SPDX-License-Identifier: 0BSD
set -eu
# Word-splitting of the delivery value below is deliberate; pathname expansion
# is not — set -f keeps glob characters in operator-supplied values literal.
set -f
umask 077
# Deliberate opt-in: seed the autonomous scheduled jobs (source surveillance and
# an optional health heartbeat) using OpenClaw's NATIVE cron. Jobs live in the
# gateway's SQLite state, so they are seeded via the CLI, not a config file;
# --declaration-key makes each seed idempotent (safe to re-run on every deploy).
#
# This is NOT run by bootstrap.sh: autonomous scheduling crosses the shipped
# fail-closed default (cron.enabled=false, PRIMARY_CHANNEL=none) and must be an
# explicit operator action after commissioning. Enable cron first: set
# config/openclaw.json cron.enabled=true, record the new artifact hash in
# config/customization-profile.json (it is a hash-pinned reviewed artifact),
# and re-run ./scripts/bootstrap.sh so the rendered runtime config reaches the
# gateway — the gateway never reads the host file directly. For channel
# delivery, configure a channel. See docs/RUNBOOK.md and CUSTOMIZATION.md.
#
# Usage:  ./scripts/schedule_jobs.sh
# Tunables (process environment only; these are NOT read from .env):
#   VC_SCAN_CRON       cron expression for the source scan   (default "0 7 * * 1-5")
#   VC_SCAN_TZ         IANA timezone                          (default "Europe/Berlin")
#   VC_SCAN_DELIVERY   optional: "--announce --channel <c> --to <target>" for a digest.
#                      Empty means NO delivery is attempted (see the --no-deliver
#                      note below), not "the harness picks something sensible".
#   VC_HEARTBEAT_DELIVERY  same, for the heartbeat digest
#   VC_HEARTBEAT_CRON  optional health-review schedule. Empty skips seeding it; it
#                      does NOT remove a heartbeat an earlier run already seeded —
#                      that keeps firing on its old cadence until you remove it with
#                      `openclaw cron rm <id>` (find the id with `openclaw cron list`).

PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="$PACKAGE_DIR/.env"
COMPOSE_FILE="$PACKAGE_DIR/docker-compose.yml"
COMPOSE_PROJECT="openclaw-lead-research-v3"

SCAN_CRON="${VC_SCAN_CRON:-0 7 * * 1-5}"
SCAN_TZ="${VC_SCAN_TZ:-Europe/Berlin}"
SCAN_DELIVERY="${VC_SCAN_DELIVERY:-}"
HEARTBEAT_DELIVERY="${VC_HEARTBEAT_DELIVERY:-}"
HEARTBEAT_CRON="${VC_HEARTBEAT_CRON:-}"

# Omitting every delivery flag does NOT mean "no delivery" upstream. For an
# isolated agent job the pinned CLI defaults deliveryMode to "announce" with
# channel "last" (cron-cli:702, --channel default at :604), and an isolated
# session has no delivery context to resolve that against: the runner either
# refuses the inherited main-session recipient or reports "Target is required",
# and without --best-effort-deliver the run is stamped status=error every time.
# The agent's research still persists, but the job looks permanently failed and
# nothing is delivered. Be explicit in both directions instead.
[ -n "$SCAN_DELIVERY" ] || SCAN_DELIVERY="--no-deliver"
[ -n "$HEARTBEAT_DELIVERY" ] || HEARTBEAT_DELIVERY="--no-deliver"

compose() {
  docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" --env-file "$ENV_FILE" "$@"
}

# Non-default agents must run in an isolated session (assertMainSessionAgentId).
compose exec -T openclaw-gateway openclaw cron add \
  --name "vc-source-scan" \
  --declaration-key "vc-source-scan" \
  --cron "$SCAN_CRON" \
  --tz "$SCAN_TZ" \
  --agent vc-chief \
  --session isolated \
  --message "Run source surveillance per standing orders: for each due watched source, screen it and route thesis-matching candidates through the normal outbound research and evidence-record path for human review. Do not contact anyone." \
  $SCAN_DELIVERY

echo "Seeded cron job: vc-source-scan ($SCAN_CRON $SCAN_TZ)."

if [ -n "$HEARTBEAT_CRON" ]; then
  compose exec -T openclaw-gateway openclaw cron add \
    --name "vc-heartbeat" \
    --declaration-key "vc-heartbeat" \
    --cron "$HEARTBEAT_CRON" \
    --tz "$SCAN_TZ" \
    --agent vc-chief \
    --session isolated \
    --message "Run the read-only health review per HEARTBEAT.md and report findings. Do not repair records or deliver notifications." \
    $HEARTBEAT_DELIVERY
  echo "Seeded cron job: vc-heartbeat ($HEARTBEAT_CRON $SCAN_TZ)."
fi

echo "Review with: docker compose -p $COMPOSE_PROJECT exec openclaw-gateway openclaw cron list"
