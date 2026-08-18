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
# Captured before the cd into the package below: a relative destination must
# resolve where the operator invoked the script, not inside the live package
# tree that recovery points are documented to stay out of.
INVOCATION_PWD="$PWD"
BACKUP_DESTINATION="${1:-}"
LOCK_OWNED=0
LOCK_TOKEN=""
MUTATION_STARTED=0
LEDGER_SNAPSHOT=""

compose() {
  docker compose -f "$COMPOSE_FILE" -p "$COMPOSE_PROJECT" \
    --env-file "$ENV_FILE" "$@"
}

cleanup() {
  status="$?"
  trap - EXIT HUP INT QUIT TERM
  if [ "$status" -ne 0 ] && [ "$MUTATION_STARTED" -eq 1 ]; then
    compose --profile tools stop openclaw-cli openclaw-gateway >/dev/null 2>&1 || true
    echo "Update or pre-update backup failed after lifecycle mutation began; consumers remain stopped. Repair the release, or restore the verified pre-update backup if its final directory was published, before restarting traffic." >&2
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
trap 'exit 1' HUP INT QUIT TERM

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
  *) BACKUP_DESTINATION="$INVOCATION_PWD/$BACKUP_DESTINATION" ;;
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

# Render before anything creates a container. The four file-backed Compose
# secrets under config/runtime/secrets/ are written only by a lifecycle render
# and are absent from a freshly exported package (git-ignored, and listed in
# manifest.json excluded_runtime_files), so a new package directory reaches
# backup.sh unrendered. backup.sh quiesces the gateway and CLI before its first
# container-creating call, which then dies on a missing bind source — taking
# production down with no recovery point. bootstrap.sh renders before its first
# Compose call for the same reason. Keep this above MUTATION_STARTED.
python3 scripts/render_channel_config.py "$ENV_FILE"

# The update-mode backup also refuses when the live migration ledger is ahead of
# the lock (a first attempt that applied migrations but never recorded the new
# lock), because stamping the old version onto a new-schema dump produces a
# recovery point that only migrate.sh rejects — after the production database
# has been dropped. That guard runs before backup.sh quiesces anything, so
# mirror it here too: otherwise MUTATION_STARTED below arms the handler that
# stops the gateway and CLI, and a guard designed to fail closed on a healthy
# running deployment takes production down on its way to reporting.
LEDGER_SNAPSHOT="$(mktemp "${TMPDIR:-/tmp}/openclaw-update-ledger.XXXXXX")"
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
  "$PACKAGE_DIR/deployment-lock.json" <"$LEDGER_SNAPSHOT" >/dev/null || {
  rm -f "$LEDGER_SNAPSHOT"
  echo "the live migration ledger is ahead of deployment-lock.json; see RUNBOOK 8" >&2
  exit 1
}
rm -f "$LEDGER_SNAPSHOT"

# backup.sh refuses when a `docker compose run` CLI one-off survives its quiesce
# stop, because such a container keeps writing the state and quarantine volumes.
# That refusal lands after the gateway is already stopped, so mirror it here
# while nothing has been touched — same reason the ledger guard above is
# mirrored. Only openclaw-cli is checked: the gateway is expected to be running
# at this point, and openclaw-cli is otherwise only ever created with
# `up --no-start`, so finding it running means a live turn.
# Capture the enumeration on its own line, the way backup.sh already does, so
# `set -e` aborts when `compose ps` itself fails. Piping it straight into grep
# made the pipeline exit status grep's alone: a failing or empty enumeration
# looked exactly like "openclaw-cli is not running" and silently disabled this
# refusal, which is the only guard between a live CLI turn and a destructive
# operation that cannot stop it.
running_services="$(compose --profile tools ps --all --status running --services)"
if printf '%s\n' "$running_services" | grep -Fxq openclaw-cli; then
  echo "openclaw-cli is running: a 'docker compose run' CLI turn does not stop" >&2
  echo "with its service and would keep writing the volumes this update backs up." >&2
  echo "Let the turn finish, then re-run." >&2
  exit 1
fi

# A crash-left rotation lock is a state docs/OPERATIONS.md documents as an
# expected leftover ("can outlive an interrupted bootstrap or update"), but
# rotate_runtime_role.sh only discovers it deep inside this script -- after the
# quiesce, after the pre-update recovery point is published, and after
# MUTATION_STARTED has armed the handler that leaves consumers stopped. Mirror
# the check here, while production is still running, the same way the ledger and
# CLI guards above are mirrored.
ROTATION_LOCK_DIR="/tmp/openclaw-lead-research-v3-rotation.lock"
# The remedy pointer below names 'First install', not 'Secrets'. The whole
# stale-lock recovery procedure -- confirm no rotation process is active, then
# remove the directory with `rm -rf` because it is not empty (it holds
# deployment.env, a verbatim copy of .env) -- sits in the rotate_runtime_role.sh
# paragraph under `## First install`. An earlier draft of this message cited
# 'Secrets', which covers .env handling, the non-database secret re-render and
# pepper/trusted-context rotation and never mentions this lock path at all: an
# operator blocked here and following that pointer landed in a section with
# nothing to act on. If the paragraph moves, move this citation with it.
if [ -e "$ROTATION_LOCK_DIR" ]; then
  echo "a database-secret rotation is running or left a stale lock: $ROTATION_LOCK_DIR" >&2
  echo "resolve it before updating; nothing has been changed. docs/OPERATIONS.md," >&2
  echo "'First install', documents the crash-left case: confirm no rotation is" >&2
  echo "active, then remove the whole directory ('rm -rf', not 'rmdir')." >&2
  exit 1
fi

# backup.sh refuses an inbox entry a recovery archive cannot represent. update.sh
# reaches that guard only through backup.sh, which runs AFTER MUTATION_STARTED
# arms the handler that leaves consumers stopped -- so on the update path the
# refusal would land with production already quiesced. Mirror it here while the
# gateway is still up, exactly as the ledger, CLI and rotation-lock guards above
# are mirrored.
#
# backup.sh is the authority for which classes are refused and why; the block
# below is its copy, differing only in the remedy's last two words. Enumerating
# the classes by hand in two places drifted once: this mirror carried three of
# backup.sh's five classes and matched the absolute entry instead of the
# inbox-relative path, so a backslash-named or hard-linked entry was refused
# only after MUTATION_STARTED, and a package installed under a directory whose
# own name held a control character had every clean inbox refused. Both were
# measured. tests/g7/test_recovery_lifecycle.py now extracts the refusal classes
# from both scripts and fails when the two sets differ, so a class added to one
# copy alone cannot ship.
inbox_reject=""
# Probe for a control character BEFORE enumerating, and never parse this probe's
# output as lines. `find` delimits its output with newlines, so an entry whose
# own name contains one is split into two fragments that are each tested
# separately -- and both can pass. Measured under dash: an entry named
# "<newline>scripts" printed as "<inbox>/" and "scripts"; the first is the inbox
# directory and the second resolves against $PACKAGE_DIR, so both are
# directories, the loop below accepted them, and a symlink the validator refuses
# reached the archive. A newline is a control character, so one probe closes the
# whole class. `-name` matches each entry's own basename and every path
# component is some entry's basename, so a control character anywhere under the
# inbox is found. Verified to behave identically under GNU find (Debian) and BSD
# find (macOS), and to leave Muller.pdf, CJK names, spaces, nested directories
# and backslash names alone.
if [ -n "$(find "$PACKAGE_INBOX" -mindepth 1 -name '*[[:cntrl:]]*' -print)" ]; then
  inbox_reject="an entry name holds a control character; list them with: find $PACKAGE_INBOX -mindepth 1 -name '*[[:cntrl:]]*'"
fi
# Enumerate on its own line so `set -e` aborts when find itself fails; a
# command substitution inside the here-document swallowed that, and an
# unreadable subtree then read as a clean inbox.
inbox_entries="$(find "$PACKAGE_INBOX" -mindepth 1)"
while IFS= read -r entry; do
  [ -n "$entry" ] || continue
  # The patterns match the inbox-relative path, not the absolute one: the
  # relative path is the member name tar writes and therefore the exact string
  # the validator judges, and matching the absolute path refuses every update on
  # a package installed under a directory whose own name carries one of these
  # characters. `inbox_relative` is backup.sh's name for it; keeping the two
  # spellings identical is what lets the g7 test compare the blocks.
  inbox_relative="${entry#"$PACKAGE_INBOX"/}"
  case "$inbox_relative" in
    # [[:cntrl:]] matches ord<32 and 127 and, unlike [![:print:]], does not
    # reject ordinary non-ASCII filenames such as Muller.pdf.
    *[[:cntrl:]]*) inbox_reject="$entry (control character in path)" ; break ;;
    # validate_recovery_archive.py rejects any member name containing a
    # backslash; such a file passes every test below, so tar happily archives
    # it and the validator fails the whole recovery point after the quiesce.
    *\\*) inbox_reject="$entry (backslash in path)" ; break ;;
  esac
  if [ -L "$entry" ]; then
    inbox_reject="$entry (symlink)"
    break
  fi
  if [ ! -f "$entry" ] && [ ! -d "$entry" ]; then
    inbox_reject="$entry (not a regular file or directory)"
    break
  fi
done <<INBOX_SCAN
$inbox_entries
INBOX_SCAN
if [ -z "$inbox_reject" ]; then
  # A hard-linked regular file passes every test above -- it really is a
  # regular, non-symlink file -- but tar emits the second name as a link member
  # and the validator then refuses the archive with "links, sparse files,
  # devices, and special entries are forbidden". There is no portable per-entry
  # link count in the shell (`find -printf '%n'` and `stat` are both non-POSIX),
  # so enumerate the offenders with `-links +1`, which is. `-type f` is not
  # optional: every directory has more than one link.
  # This deliberately over-refuses one case: a file whose second name lies
  # outside the inbox is archived by tar as an ordinary member, because tar
  # only emits a link member for an inode it has already written. Narrowing to
  # links wholly inside the inbox needs inode grouping that POSIX find cannot
  # express, and the over-refusal is cheap -- nothing has been stopped, and the
  # operator detaches the entry with
  #   cp <entry> <entry>.detached && mv <entry>.detached <entry>
  # which leaves the content byte-identical and drops the link count to 1.
  # NOT `cp --remove-destination <entry> <entry>`: an earlier version of this
  # comment said that, and GNU cp refuses it with "are the same file".
  inbox_hardlinks="$(find "$PACKAGE_INBOX" -mindepth 1 -type f -links +1)"
  while IFS= read -r entry; do
    [ -n "$entry" ] || continue
    inbox_reject="$entry (hard link: the file has more than one name)"
    break
  done <<HARDLINK_SCAN
$inbox_hardlinks
HARDLINK_SCAN
fi
if [ -n "$inbox_reject" ]; then
  printf '%s\n' "package inbox holds an entry a recovery archive cannot represent: $inbox_reject" >&2
  echo "remove or relocate it before updating; nothing has been stopped." >&2
  exit 1
fi

# Hold one lifecycle lock from the quiesced old-state recovery point through the
# new image/schema health checks. A failed update never restarts a mixed system.
MUTATION_STARTED=1
OPENCLAW_LIFECYCLE_LOCK_TOKEN="$LOCK_TOKEN" OPENCLAW_BACKUP_LEAVE_QUIESCED=1 \
  OPENCLAW_BACKUP_COMPATIBLE_LOCK=1 \
  ./scripts/backup.sh "$BACKUP_DESTINATION"
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

# State the exit state the script actually leaves, not an aspiration. The
# readiness probes above require a running gateway, so by this line the gateway
# is up -- "before enabling traffic" told the operator traffic was still gated
# when it was not, and there is no step here that gates it.
#
# Branch on the channel instead of asserting one. PRIMARY_CHANNEL=none is a
# supported steady state, not just a bootstrap placeholder: docs/RUNBOOK.md 5.5
# tells an operator with no external channel to retain it, and
# render_channel_config.py renders the inert base configuration for it -- no
# channels, no bindings, nothing listening. An unconditional "its configured
# channel is already live" therefore stated the opposite of the truth on such a
# deployment, in the one message whose entire purpose is to state the truth, and
# sent the operator to stop a gateway that was accepting nothing. check_env.sh
# above has already proved PRIMARY_CHANNEL is present and is one of
# none/slack/teams/discord/telegram, and check_env.py rejects quoting,
# whitespace and duplicate keys in .env, so this literal read is exact.
PRIMARY_CHANNEL_VALUE="$(sed -n 's/^PRIMARY_CHANNEL=//p' "$ENV_FILE" 2>/dev/null | head -n 1)"
if [ -n "$PRIMARY_CHANNEL_VALUE" ] && [ "$PRIMARY_CHANNEL_VALUE" != none ]; then
  echo "Update completed from a quiesced pre-update recovery point. The gateway is running on the new release and its configured channel ($PRIMARY_CHANNEL_VALUE) is already live; the CLI container exists but is stopped. Re-run every affected G8 live gate now. To hold traffic while you do, stop the gateway first: docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env stop openclaw-gateway"
else
  echo "Update completed from a quiesced pre-update recovery point. The gateway is running on the new release with no channel configured (PRIMARY_CHANNEL=$PRIMARY_CHANNEL_VALUE), so it is accepting no external traffic; the CLI container exists but is stopped. Re-run every affected G8 live gate now."
fi
