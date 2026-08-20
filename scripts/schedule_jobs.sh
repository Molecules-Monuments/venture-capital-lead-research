#!/bin/sh
# SPDX-License-Identifier: Apache-2.0
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
#   VC_ALLOW_DISABLED_SCHEDULER  set to 1 to seed even though cron.enabled is
#                      false. The default refuses, because a job seeded into a
#                      disabled scheduler can never fire.
#   VC_HEARTBEAT_CRON  optional health-review schedule. Empty skips seeding it; it
#                      does NOT remove a heartbeat an earlier run already seeded —
#                      that keeps firing on its old cadence until you remove it with
#                      `openclaw cron rm <id>` (find the id with `openclaw cron list`).

PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
ENV_FILE="$PACKAGE_DIR/.env"
COMPOSE_FILE="$PACKAGE_DIR/docker-compose.yml"
COMPOSE_PROJECT="vc-lead-research-v3"

# The 07:00 default starts the scan an hour before the 08:00-19:00 Mon-Fri
# window in workspaces/vc-chief/vc/notification_policy.md, so the digest is
# ready at start of business. That window is policy the agent reasons against
# (the channel renderer rebinds it to the operator's TZ); the gateway's cron
# scheduler does not read that workspace document, so a job seeded below fires
# on the schedule handed to `openclaw cron add`. With VC_SCAN_DELIVERY unset the
# run is stamped --no-deliver below and nothing is dispatched at all; if you set
# it, put VC_SCAN_CRON inside the window your own notification_policy.md states.
#
# Monday through Friday the default's successive fires sit 24 h apart, which is
# exactly the `daily` cadence boundary in signal_source_is_due(): the interval
# must have fully elapsed since the previous claim, and the claim stamps
# last_scanned_at with clock_timestamp(), later than the now() that judged the
# source due. So a source registered `--cadence daily` is skipped on the next
# weekday unless run-to-run timing jitter starts the scan later than the
# previous claim landed (the Friday-to-Monday gap is 72 h and clears it). Give
# VC_SCAN_CRON a sub-daily schedule before registering a daily source: the
# claim lands on the first fire more than 24 h after the previous one, so an
# evenly spaced schedule of period P settles at the smallest multiple of P
# strictly above 24 h -- 25 h for an hourly "0 * * * *", 36 h for a
# twelve-hourly one. See CUSTOMIZATION.md and docs/RUNBOOK.md section 10.
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

# Seeding a job into a disabled scheduler leaves a job that can never fire. The
# upstream `cron add` warns about that but still exits 0, so an automated
# commissioning script would record a success for work that will not happen.
# Check first and refuse, naming the step that was skipped: the documented
# opt-in enables cron (RUNBOOK steps 1-3) BEFORE this script (step 4).
#
# `openclaw cron status --json` returns {enabled, storePath, storage,
# sqlitePath, jobs, nextWakeAtMs} on the pinned 2026.7.1 image.
scheduler_status="$(compose exec -T openclaw-gateway openclaw cron status --json)" || {
  echo "cannot read cron scheduler status from the gateway; is the deployment healthy?" >&2
  exit 1
}
if ! printf '%s' "$scheduler_status" | grep -Eq '"enabled"[[:space:]]*:[[:space:]]*true'; then
  if [ "${VC_ALLOW_DISABLED_SCHEDULER:-}" = "1" ]; then
    echo "warning: cron scheduler is disabled; seeding anyway because VC_ALLOW_DISABLED_SCHEDULER=1." >&2
  else
    cat >&2 <<'MESSAGE'
cron scheduler is disabled in the Gateway; refusing to seed jobs that cannot fire.

Enable it first (docs/RUNBOOK.md, "four-step opt-in"):
  1. set config/openclaw.json cron.enabled: true
  2. re-pin it: python3 -B scripts/init_customization.py --update-hashes
     and python3 -B scripts/build_release_manifest.py
  3. ./scripts/bootstrap.sh   (the gateway reads the rendered volume copy,
                               never the host file)
  4. re-run this script

To seed deliberately ahead of enabling, set VC_ALLOW_DISABLED_SCHEDULER=1.
MESSAGE
    exit 3
  fi
fi

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
