# Operations — Version 3.0

## State ownership

Postgres is authoritative for leads, evidence, compiled truth, decisions,
approvals, notifications, workflow audit, entity resolution, verified channel
principals, consumed trusted-context scopes, and bounded per-user preferences.
OpenClaw's state volume owns sessions, Task Flow (`state/openclaw.sqlite`),
Lobster resume state, inbound-media staging, and exec-approval socket metadata.
Conversational Markdown/vector memory and automatic memory flush are disabled;
there is no chief-memory volume. Runtime config and quarantine use stable named
volumes (`OPENCLAW_RUNTIME_CONFIG_VOLUME` and `VC_QUARANTINE_VOLUME`).

## First install

1. Complete `CUSTOMIZATION.md` and create a reviewed
   `config/customization-profile.json`.
2. Copy `.env.example` to `.env`, populate the required values, and set mode
   `0600`. Generate a dedicated 64-hex-character `BACKUP_HMAC_KEY`; never reuse
   it, store it in a recovery point, or discard a key while its backups remain.
3. Run `scripts/check_env.sh`, then `python3 -B scripts/check_customization.py
   config/customization-profile.json .env`; the publication example must fail
   closed and every reviewed runtime value must match the deployment
   environment. Unknown
   keys, duplicate keys, symlinks, non-`0600` mode, differing ambient values,
   Compose substitution/quote/comment syntax, and ambient Compose steering
   variables fail closed. Use literal `KEY=VALUE` lines only.
4. Run `scripts/bootstrap.sh`.
5. Run the release and security checks described in `RUNBOOK.md`.
6. If using a channel, select one profile, configure its stable multi-user
   allowlist, and complete its text, preference-isolation, document-attachment,
   replay, restart, and rollback matrix. The base configuration enables no
   channel.

The package deliberately does not mount `/var/run/docker.sock`, run privileged containers, publish Postgres, or claim nested Docker sandboxing. Operators requiring mutually hostile tenants must use separate gateways/hosts.

The reviewed workspaces and approval seed are baked into the derived image.
The host-rendered config remains a non-symlink regular file at mode `0600`.
Only `openclaw-state-init` receives that file-backed Compose config. The
one-shot service has no network, a read-only root filesystem, and only the
temporary `CHOWN`, `DAC_OVERRIDE`, and `FOWNER` capabilities; it validates the
document and atomically copies it to the dedicated runtime-config volume as a
node-owned mode-`0400` file. It also loads the reviewed approval seed
into the state database unconditionally — `approvals set` replaces the row
outright, so re-running it is idempotent — removes any legacy
`exec-approvals.json` and asserts its absence, and checks its exact allowlist
by reading the stored row back. Gateway and
CLI run non-root with all capabilities dropped, mount the runtime-config volume
read-only, and select `/home/node/.openclaw-config/openclaw.json` with
`OPENCLAW_CONFIG_PATH`. Do not add host workspace or state-path config bind
mounts, or grant the file-backed Compose config to long-running services.

Compose applies explicit CPU, memory, PID, tmpfs, and local json-file rotation
bounds. Treat their `.env` values as capacity gates: load-test before raising
them and investigate OOM/restart evidence rather than disabling the bounds.

Bootstrap and every update take the package-wide lifecycle lock and run `scripts/rotate_runtime_role.sh`. The script takes its database-rotation lock, copies `.env` once into a mode-`0600` private snapshot, re-validates that snapshot (`check_env.sh`), validates the customization binding against it and re-renders the runtime config and all four secret files from it (`check_customization.py`, then `render_channel_config.py`), then stops all declared database-secret consumers and force-recreates Postgres so its file-backed Compose secrets are re-read. It temporarily sets the runtime role to `NOLOGIN`, evicts existing owner/runtime sessions, changes both credentials through `psql`'s protected `\password` path, removes role memberships in both directions, resets role settings, and reasserts `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`, `NOREPLICATION`, and `NOBYPASSRLS` before restoring login.

The reconciler proves both new credentials over TCP and proves that an invalid password is rejected. The script then applies any pending schema migrations via `scripts/migrate.sh` under its checksum ledger, re-runs the `openclaw-state-init` one-shot so the re-rendered config reaches the runtime-config volume, and only then force-recreates the gateway and stopped CLI container. Final `vcops db-check` probes run from both consumer images. Any failure after rotation starts stops the gateway and CLI. Changing either database password without this complete reconciliation is not a valid rotation. Do not run long-lived Compose one-offs or independent backend clients during this maintenance operation; runtime sessions are deliberately terminated. If a host crash leaves `/tmp/vc-lead-research-v3-rotation.lock`, confirm that no rotation process is active, then remove the whole directory (`rm -rf`, not `rmdir` — it is not empty) before retrying: it holds `deployment.env`, a mode-`0600` verbatim copy of `.env` carrying both database passwords, the gateway token, the approval pepper, the trusted-context key, the backup HMAC key, and every provider and channel credential. Only the script's own exit trap removes it, which a crash never runs — and because bootstrap and update both call `rotate_runtime_role.sh`, that copy can outlive an interrupted bootstrap or update as well as a direct rotation.

Both database passwords must be independent 24-128 character base64url-safe values (`A-Z`, `a-z`, `0-9`, `_`, `-`); this keeps Compose, `psql`, passfiles, and recovery handling unambiguous. This package requires Docker Compose, not `docker stack deploy`: its file-backed secret sources are Compose-only. `docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env config --quiet` is a mandatory compatibility preflight and the lifecycle commands require support for `up --wait`, `--force-recreate`, `--no-deps`, `--no-start`, and `run --rm`.

Backup, restore, update, bootstrap, and direct role rotation share `/tmp/vc-lead-research-v3-lifecycle.lock`. Nested update/bootstrap operations pass a private owner token that is checked against the mode-`0700` lock directory; setting a boolean environment flag cannot bypass the lock. If a host crash leaves the directory, confirm no lifecycle process is active — the lock directory's `owner` file names the holder as `<operation>:<pid>`, so read it (`cat /tmp/vc-lead-research-v3-lifecycle.lock/owner`) and check that PID with `ps`. A dead holder PID is **not** sufficient on its own: the named script may have exited while the `psql`, `pg_restore`, `docker compose` or `migrate.sh` child it launched is still running against the production database, and killing the parent does not stop the SQL a child has already streamed. Run the path scan below in **both** branches and require it to be empty before you delete anything. Then remove the whole directory with `rm -rf /tmp/vc-lead-research-v3-lifecycle.lock`; `rmdir` fails while the `owner` file is present. A lock directory with **no** `owner` file is an acquisition interrupted between the `mkdir` that creates the lock and the write that names its holder: each script does those two steps in that order, so a signal in that window leaves the directory behind before its `owner` line is written. That state names no PID, so the `cat`/`ps` step above dead-ends — fall back to looking for a running lifecycle script by path, and if nothing is running remove the directory the same way (`rmdir` also succeeds here, the directory being empty):

```sh
ps -eo pid,args \
  | grep -E 'scripts/(bootstrap|update|backup|restore|rotate_runtime_role|migrate)\.sh' \
  | grep -v grep
# no output means no lifecycle script is running
```

Check for crash-left staging at the same time: a backup interrupted before publishing — including update's pre-update backup — leaves a `.<destination-name>.partial.<pid>` directory beside the intended destination, and an interrupted `restore.sh` leaves a `${TMPDIR:-/tmp}/openclaw-restore-validation.*` directory. Both hold an unpublished copy of the recovery point (database dump, sessions, continuations) under the same restricted-operational-data mandate as the backup itself, and only the scripts' own exit traps remove them, which a crash never runs — delete them after confirming no lifecycle process is active. A crashed `restore.sh` also leaves its disposable validation database inside the production cluster, holding a full copy of the backup's data and surviving a host reboot that clears `/tmp`; list and drop any leftover once no lifecycle process is active:

```sh
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
  exec -T postgres psql -X -w --username openclaw_owner --dbname postgres \
  --tuples-only --no-align --command \
  "SELECT datname FROM pg_database WHERE datname LIKE 'openclaw_restore_validate_%'"
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
  exec -T postgres dropdb --username openclaw_owner --force <name>
```

Check the database for work the dead script left running, before touching either
lock. Killing a lifecycle script does not stop SQL it has already streamed: the
`psql` process runs **inside the Postgres container**, so it survives a `kill -9`
on the host script, keeps the migration advisory lock, and can still commit.
A leftover session is therefore the one state in which removing a lock and
retrying causes two writers to overlap. The probe below is deliberately not
scoped to the `openclaw` database, and connects through `postgres`: `restore.sh`
does part of its work in its own `openclaw_restore_validate_%` database and part
through the `postgres` maintenance database (`dropdb --force openclaw` followed
by `createdb openclaw`), so a `datname = 'openclaw'` filter misses the
validation restore and the drop/create window entirely, and a connection to
`openclaw` can itself fail because that database is momentarily gone. `pg_stat_activity` is
server-wide, and `usename = 'openclaw_owner'` already excludes the background
workers and the gateway runtime role:

```sh
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
  exec -T postgres psql -X -w --username openclaw_owner --dbname postgres \
  --tuples-only --no-align --command \
  "SELECT pid, datname, state, xact_start, left(query, 80) FROM pg_stat_activity
   WHERE usename = 'openclaw_owner'
     AND state <> 'idle' AND pid <> pg_backend_pid()"
# no output means no openclaw_owner session is executing anywhere in the cluster
```

If a row comes back, let it finish or terminate it deliberately
(`SELECT pg_terminate_backend(<pid>)`) and re-check, before removing any lock or
re-running any lifecycle script.

Every script pins both the absolute Compose file and project name, so invoking it from a different current directory cannot select another stack.

## Operator administration lane

Several routine duties can only be performed on the host-operator lane, which is
deliberately absent from the agent exec allowlist. It lives inside the gateway
image, so reach it with `compose exec` from the package directory:

```sh
compose() {
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env "$@"
}
operator() {
  compose exec -e VCOPS_OPERATOR_ID="$OPERATOR_ID" openclaw-gateway \
    /workspaces/vc-chief/vc/bin/vcops-operator "$@"
}
```

`VCOPS_OPERATOR_ID` is the stable ID of the human acting. It is passed per
invocation and is **not** an `.env` key — `check_env.py` rejects it there as an
unknown variable. Every command below emits one JSON object.

```sh
OPERATOR_ID=partner-1

# Governance/skill proposals (RUNBOOK §7 weekly review).
operator proposal-list --status submitted
operator proposal-decide --proposal-id <id> --decision accept \
  --reviewer "$OPERATOR_ID" --note "<why>"

# Watchlist: re-enable or reclassify a source a model lane may not touch.
operator source-list
operator source-watch --name "<name>" --uri "<https://…>" \
  --source-class news_rss --cadence daily --confidentiality internal
operator source-unwatch --uri "<https://…>"
operator source-scan --limit 50

# Database reachability, from the gateway and from a one-off CLI container.
compose exec openclaw-gateway /workspaces/vc-chief/vc/bin/agent/vcops db-check
compose --profile tools run --rm --no-deps \
  --entrypoint /workspaces/vc-chief/vc/bin/agent/vcops openclaw-cli db-check
```

There is no `vcops` on the host or on the image's `PATH`; always use the
absolute wrapper path. The `openclaw-cli` service sets its own entrypoint, so
the `--entrypoint` override above is required.

### Erasing a lead

`data-erase-lead` is approval-gated: request an approval, have a *second*
operator decide it, then spend the returned token exactly once.

Four details decide whether this works, and all four are checked server-side:

- `--scope` and `--action-preview` are **JSON objects**, not display strings.
- `--scope` must bind `lead_id` to the lead being erased. The database
  re-verifies this against the consumed approval's own stored scope, so an
  approval reviewed for one lead can never erase another.
- `--action` must be exactly `data.erase_lead`. That is the action name
  `consume_approval_and_erase_lead` consumes; anything else is refused with
  `authorization_denied: approval scope does not match governed action`.
- The decide step requires `VCOPS_OPERATOR_ID` to equal `--approver`, so the
  **approver runs it under their own operator identity** — not the requester's.
  The `operator()` helper above pins `VCOPS_OPERATOR_ID="$OPERATOR_ID"`, so the
  approver needs their own invocation.

`--scope`, `--target-system`, and `--payload-hash` must be identical in the request and the erasure
(the scope is compared by hash, so key order does not matter but values must
match). Define them once and reuse the variables:

```sh
LEAD_ID=<lead-id>
SCOPE="$(printf '{"lead_id": %s}' "$LEAD_ID")"
PREVIEW="$(printf '{"summary":"erase lead %s"}' "$LEAD_ID")"
sha256_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi
}
PAYLOAD_HASH="$(printf '%s' "$PREVIEW" | sha256_stdin | awk '{print $1}')"

# 1. Requester mints the approval. The raw token is returned exactly once.
operator approval-request --idempotency-key "erase-$LEAD_ID-$(date +%s)" \
  --action data.erase_lead --scope "$SCOPE" --action-preview "$PREVIEW" \
  --target-system vcops --lead-id "$LEAD_ID" --payload-hash "$PAYLOAD_HASH" \
  --requested-by "$OPERATOR_ID" --expires-minutes 60

# 2. The SECOND approver decides, under their own identity. Note this does not
#    use operator(): VCOPS_OPERATOR_ID must be the approver, not the requester.
compose exec -e VCOPS_OPERATOR_ID="<second-approver-id>" openclaw-gateway \
  /workspaces/vc-chief/vc/bin/vcops-operator approval-decide \
  --request-id <request-id> --decision approve \
  --approver "<second-approver-id>" --approval-channel operator-console --reason "<why>"

# 3. Spend the token once, atomically with the erasure.
operator data-erase-lead --lead-id "$LEAD_ID" --token "<token>" \
  --scope "$SCOPE" --target-system vcops --payload-hash "$PAYLOAD_HASH" \
  --transaction-id "$(python3 -c 'import uuid; print(uuid.uuid4())')" --actor "$OPERATOR_ID"
```

A replay of step 3 is refused (`approval is not consumable (status=consumed)`).
`approval-consume` on its own is always refused by contract: an approval may only
be spent in the same transaction as the mutation it authorizes.

Approver and requester must be different stable identities. That separation is
deployment policy you uphold, not a database constraint: what the system
enforces is that the decision is taken under the approver's *own* operator
identity (`VCOPS_OPERATOR_ID` must equal `--approver`), which is why step 2
cannot be run through the requester's shell. Every request and decision is
recorded with both identities, so the separation is auditable after the fact.

Rotating
`VCOPS_APPROVAL_PEPPER` invalidates every approval that has not yet been
consumed, including approved ones, because the pepper HMACs the stored token
digest. `data-erase-lead` is the audited entry point to an erasure procedure and
does not by itself reach backups, exports, or anything outside this database —
see `workspaces/vc-chief/vc/data_retention.md` for what it covers.

## Health

- `/healthz` is liveness only.
- `/readyz` is readiness and is used by Compose.
- `docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env ps` must show Postgres and the gateway healthy before workflows are accepted.
- Task Flow rows in `queued`, `running`, `waiting`, or `blocked` must be inspected during incidents; cancellation is sticky and revisions must be honored.

## Backup

Run `scripts/backup.sh <new-directory>` while the stack is healthy. The parent must already exist, the named destination must not exist, and the canonical destination must not equal, contain, or sit beneath the package `inbox/`; keep recovery points outside every live tree they capture or replace. The script takes the lifecycle lock, records whether the gateway was running, verifies that the Docker image IDs still match the deployment lock and that both pinned upstream digests are present, stops both gateway and CLI state consumers, proves Postgres readiness, and captures one named recovery window. A normal backup waits for and database-checks the gateway before publishing the result; an update deliberately keeps consumers stopped until the new release passes health checks.

The recovery point contains a custom-format Postgres dump (including preference
state and forget markers); OpenClaw state including sessions, inbound media,
Task Flow SQLite, and Lobster continuations; read-only operator inbox originals
as they stand in the package directory the script is run from;
the named quarantine volume; a database-derived local-artifact URI/hash
inventory; package version; deployment/image/release lock; format-3 manifest;
checksums; and `BACKUP_AUTHENTICATION`. Backup verifies each database artifact
against staged bytes and authenticates the exact checksum manifest with
HMAC-SHA-256 before atomic publication.

Generated `openclaw.json`, any legacy `exec-approvals.json`, the volatile `exec-approvals.sock`, `.env`, database secret files, and provider/channel credentials are intentionally excluded. The reviewed exec allowlist is not a file in the recovery point on the `2026.8.1` base: it lives in the `exec_approvals_config` row of the state database, which the state archive does capture, and the harness's socket token lives in that same row. The target's reviewed approval seed is therefore re-asserted from the read-only image-baked `/opt/openclaw-seed/exec-approvals.json` and read back from the row before the restored gateway starts — a restore that only checked for the absent file would prove nothing. The state archive can nevertheless contain sessions and Lobster continuation material and the database dump contains business data: protect the entire backup as restricted operational data.

The package's recovery algorithms and tamper tests are release evidence. A live
isolated-host restore remains environment-specific commissioning evidence and
was explicitly excluded from this package-readiness effort.

## Update

1. Review upstream release notes and migration requirements.
2. Change pinned references only in a reviewed release revision; never use `latest` or `main`.
3. Carry the deployed revision's runtime state into the new package directory before running anything: `deployment-lock.json`, `.env`, `config/customization-profile.json`, `config/connectors.json` if you use connectors, and every customized policy artifact. **`config/openclaw.json` and `config/connectors.json` are release-owned in 3.0.1: merge your edits into the new tree’s copies rather than copying the 3.0.0 files across.** Both old shapes are startup-fatal on 2026.8.1 (exit 78) and neither is caught before the migrations run — see the 3.0.1 entry in `CHANGELOG.md` for the connector key and unit conversion. `inbox/` is bind-mounted from the package directory (`docker-compose.yml`, `./inbox:/inbox:ro`), not held in a named volume, so a new package directory starts with the shipped placeholder alone. Copy the deployed revision's `inbox/` contents across too if you want the operator lane to keep seeing them; the pre-update recovery point captures whatever the new directory's `inbox/` holds when `update.sh` runs. Operator payload under `inbox/` is excluded from `manifest.json` and tolerated by `verify_release.py --pristine`, so carrying it across does not affect the re-pin. `update.sh` runs `check_env.sh` and `check_customization.py` before it takes the lifecycle lock, and the profile's twenty artifact hashes are re-checked against the new tree — so the profile has to be re-pinned once the artifacts are across. Before re-pinning, run `python3 -B scripts/check_customization.py config/customization-profile.json .env` and read the `reviewed artifact changed after review: <path>` lines it prints. Account for each path it names — a deliberate edit of yours, or a change this release made to a shipped artifact. A path you cannot account for is a customization that was not carried across; re-pinning it is how you lose it, silently, because the re-pin reports only a count and no later gate can see the reversion (RUNBOOK §9, "Never regenerate hashes around a change you cannot account for"). Only then re-pin with `python3 -B scripts/init_customization.py --update-hashes`.
4. **Produce the new reviewed package and manifest and rerun every offline gate BEFORE running the update**, `docs/RUNBOOK.md` §8 opens by requiring exactly that ordering — "before any update ... produce a new reviewed package/manifest, and rerun every offline gate" — but names no commands, so the concrete sequence is this checklist's own: `python3 -B scripts/build_release_manifest.py`, then `python3 -B scripts/verify_release.py --pristine`, then `python3 -B scripts/verify_offline.py`. The re-pin is not optional and is not the same step as the profile re-pin above: the profile pins twenty reviewed artifacts, `manifest.json` pins every declared file, and RUNBOOK §9 reads a `--pristine` mismatch as tampering. Running the gates only after `update.sh` — as an earlier version of this checklist did — certifies a tree that has already been deployed.
5. Run `scripts/update.sh <new-pre-update-backup-directory>`. The update-only compatible-backup mode validates the old lock against the still-live image IDs and writes both backup `VERSION` and `BACKUP_MANIFEST.package_version` from that lock, never from the newly placed package. The old lock and its matching old version are therefore embedded together in the pre-update recovery point. If a first update attempt failed *after* its migrations applied but before it recorded the new lock, the deployment's schema is already ahead of that old lock — a retry's pre-update backup would otherwise stamp the old version onto a new-schema dump, and restoring it would fail only at `migrate.sh`, after the production database was dropped. `backup.sh` refuses in that state in **either** mode — the ledger comparison runs before the compatible-lock branch, because the same drift makes a direct backup's VERSION stamp wrong too — naming the applied migration the lock cannot account for; the valid rollback target is then the **first** attempt's recovery point. The script holds one lifecycle lock from that quiesced point through build, secret/role reconciliation, migration, consumer reconciliation, the readiness probes, and recording the new lock — that is the order it executes them in. Do not set `OPENCLAW_BACKUP_COMPATIBLE_LOCK` manually; backup rejects it unless the private update lock and quiesced mode are both active.
6. Run all offline and live release gates again, now against the updated deployment.
7. Confirm the rebuilt image actually carries the policy artifacts you carried across: `python3 -B scripts/record_images.py --validate-baked-sources deployment-lock.json`. Do not re-run the bare recorder first: `update.sh` already recorded the new image IDs and digests immediately after its build, and a standalone `python3 -B scripts/record_images.py` would re-stamp `baked_sources_sha256` from the current tree and make this step pass unconditionally (RUNBOOK §4). `workspaces/` is image-baked and never bind-mounted, so a carried-across thesis or rubric that was not present at build time is silently absent from the running gateway (`CUSTOMIZATION.md`, "Policy edits reach the deployment only through a rebuild").

## Rollback and restore

`scripts/restore.sh <backup-directory> --confirm-destructive-restore` is destructive. Prepare an isolated target with the exact package revision first: verify its external provenance and embedded inventory, create and validate `.env` with `PRIMARY_CHANNEL=none`, the matching retained backup HMAC key, and an `OPENCLAW_STATE_ARCHIVE_MAX_BYTES` at least as large as the value in force when the backup was written (the backup records its bound in `BACKUP_MANIFEST`, and `restore.sh` fails closed pre-mutation naming the variable if the target's effective bound is smaller), then prepare a customization profile for that host — `bootstrap.sh` and `restore.sh` both validate the profile against the `.env` before doing anything, and the profile is deliberately not inside the backup. Copy your reviewed policy artifacts and `config/customization-profile.json` across, set `channels.selected` to `none` and `approvals.allowed_channel_ids` to `[]` so they match the inert `.env`, keep `organization.timezone`, `models.*` and `search.*` byte-identical to that `.env`. Then, before re-pinning, run `python3 -B scripts/check_customization.py config/customization-profile.json .env` and read the `reviewed artifact changed after review: <path>` lines it prints. Account for each path it names — a deliberate edit of yours, or a change this release made to a shipped artifact. A path you cannot account for is a customization that was not carried across; re-pinning it is how you lose it, silently, because the re-pin reports only a count and no later gate can see the reversion (RUNBOOK §9, "Never regenerate hashes around a change you cannot account for"). Only then re-pin with `python3 -B scripts/init_customization.py --update-hashes`, and confirm `python3 -B scripts/check_customization.py config/customization-profile.json .env` passes. Then run `scripts/bootstrap.sh` (or equivalently load/build the exact derived CLI image, start a healthy package Postgres service, initialize state, and run `scripts/record_images.py`), and retain its local `deployment-lock.json`. Only then run restore. The canonical backup source and private validation staging must not equal, contain, or sit beneath the package `inbox/`; the script rejects that overlap before mutation so replacing the inbox cannot delete the recovery point or its staged source. Before any verification it copies every backup member into private staging with a single read of each; the operator-writable backup directory is never read again after that point. It then authenticates the staged checksum manifest with HMAC-SHA-256 and verifies every staged member's checksum against that authenticated manifest, so the bytes that were authenticated are exactly the bytes that get restored — there is no verify-then-reread window. From the staged copies it validates the checksum inventory, package version, the target's own lock against the exact manifest/upstream/image-reference/migration contract, the backup's lock against the package/upstream/migration contract (deliberately excluding the manifest digest, so a recovery point taken before a policy re-pin stays restorable), and the target's live Docker image IDs and pinned upstream digests against its local lock; structurally rejects archive traversal, links, devices, control-character or duplicate paths, sparse files, and configured entry/size/expansion-limit violations; safely extracts every state/artifact archive into private staging (removing each staged archive after extraction to bound peak staging space); restores the database dump into a disposable validation database; and proves its database artifact inventory resolves to the staged inbox/quarantine bytes. Production replacement — including the destructive `pg_restore` — streams only from that validated staging tree, never from the operator-writable original archive. Staging therefore needs temporary space for the whole backup plus the fully extracted state, inbox and quarantine trees — and, after mutation begins, a second compressed-plus-extracted copy of the state and quarantine tiers that restore reads back from the deployment. Only the three originally staged archives are deleted after extraction; the extractions themselves must survive because later steps read them, and the `active-state.tar.gz` and `active-quarantine.tar.gz` copies restore writes back from the deployment after mutation begins are never removed — so an ENOSPC there strikes after the production database has already been replaced. Size `${TMPDIR:-/tmp}` at roughly the database dump + (2 × uncompressed state) + uncompressed inbox + (2 × uncompressed quarantine) + one compressed copy each of the state and quarantine tiers; raising `OPENCLAW_STATE_ARCHIVE_MAX_BYTES` raises the state terms with it, up to 100 GiB per copy. Only then does it stop every state consumer, recreate the production database, replace OpenClaw state, inbox, and named quarantine content, reject any migration ledger row unknown to this package, apply pending migrations plus their checksums in transactions, reconcile roles, recreate secret consumers, wait for readiness, and run database checks from both images.

Run restore only in an approved maintenance window with a second current backup and a matching reviewed package. Migration runners serialize on a PostgreSQL transaction-scoped advisory lock and make their ledger decision under that lock; application and checksum registration commit together. If a failure occurs after mutation begins, the script leaves gateway and CLI stopped; do not manually start a partial system. Repair or retry the verified recovery point. Script success proves the package path, not the specific target environment; deployment commissioning may additionally exercise `doctor`, Task Flow audit, exact-once Lobster resume/cancel, models, and a selected channel.

For an image-only rollback, restore the previously reviewed image reference and package revision together. Never run an older binary against a newer schema unless the release notes explicitly state backward compatibility. On the `2026.8.1` base that rollback is not available for the OpenClaw state volume at all: the one-shot `openclaw-state-init` service — a `service_completed_successfully` precondition of the gateway — moves `state/openclaw.sqlite` from `PRAGMA user_version` 1 to 15 before the gateway is allowed to start (measured; a read-only `openclaw approvals get` under `2026.8.1` is enough), and a `2026.7.1` gateway then exits 1 against that volume with `uses newer schema version 15; this OpenClaw build supports 1`. Restore the recovery point instead, and do not read a `2026.7.1` CLI's exit 0 as proof: the CLI downgrades the same refusal to a migration warning and reports an empty exec allowlist at `security: "full"`.

## Secrets

Keep `.env` outside version control and restrict it to the deployment operator.
Rotate gateway, model/search, trusted-context, provider, and channel secrets
after suspected exposure.

Editing `.env` is not enough, and `docker compose restart` re-reads nothing:
`OPENCLAW_GATEWAY_TOKEN` is baked into the service environment at container
creation, and the four files under `config/runtime/secrets/` are only rewritten
by a lifecycle render. The sequence for the non-database secrets is:

```sh
./scripts/check_env.sh .env
python3 -B scripts/render_channel_config.py .env
docker compose -f docker-compose.yml -p vc-lead-research-v3 \
  --env-file .env up -d --force-recreate
docker compose -f docker-compose.yml -p vc-lead-research-v3 \
  --env-file .env --profile tools up --force-recreate --no-deps --no-start openclaw-cli
```

The last line is not redundant. `openclaw-cli` sits behind the `tools` profile,
so the `up -d --force-recreate` above does not touch it, and the stopped
container bootstrap created keeps the `OPENCLAW_GATEWAY_TOKEN` and
provider/channel values it was created with — visible to anyone who can run
`docker inspect`. It is the same command `scripts/rotate_runtime_role.sh` runs
for the same reason; it recreates that container against the new `.env` and
leaves it stopped, as bootstrap left it. `./scripts/rotate_runtime_role.sh` does
the same rendering and the same two recreations, but it is not a smaller step:
it also rotates both database passwords and runs `migrate.sh` (see below).

A trusted-context rotation invalidates outstanding capabilities; after the
force-recreate, prove a new document/preference operation. Note that rotating
`VCOPS_APPROVAL_PEPPER` also invalidates every approval that has not yet been
consumed — `pending` *and* `approved`-but-unconsumed alike, because the pepper
HMACs the approval token and rotation changes every stored digest. Issue those
again after rotation.
Rotate both database values together through `scripts/rotate_runtime_role.sh`. Because rotation re-renders the runtime config from `.env` and runs `migrate.sh`, a direct rotation also deploys any other `.env` changes and any pending migrations present in the tree — rotate from a reviewed tree, not mid-edit.
The Teams profile withholds Graph permissions, `sharePointSiteId`, delegated
auth, and SSO. All profiles disable config writes, chat exec approvals,
administrative commands, and action tools while permitting governed
PDF/PPTX/XLSX/CSV intake. Unsupported media is blocked before model input.

## Decommissioning a deployment

Take a final recovery point first if the data is still needed; the sequence
below destroys it. **`docker compose down --volumes` is not sufficient.**
`openclaw-cli` sits behind `profiles: ["tools"]`, so a `down` without that
profile neither removes the container `bootstrap.sh` created for it nor —
because that container still references them — **three** of the four named
volumes:

- `openclaw-state` — sessions, inbound media, Task Flow SQLite, Lobster
  continuation;
- `vc-quarantine` — copies of uploads the extract lane rejected *and could
  copy*. A rejection a shipped workflow reaches at `document-preview` writes
  nothing (the read lane performs no mutation), and in the extract lane an
  oversized or unreadable input yields `materialized: false` and no copy.
  `quarantine_write_failed` is narrower — it reports that *this* rejection
  published nothing new; because quarantine names are content-addressed, a copy
  and marker published by an earlier rejection of the same bytes are
  deliberately retained. The volume can therefore be empty after real
  rejections, and can equally still hold the bytes of a rejection that reported
  `materialized: false`; `RUNBOOK.md` §9, "Malicious document", says how to
  read both;
- `openclaw-runtime-config` — the rendered effective configuration.

Only `postgres-data` is actually removed. Compose does say so, in lines that are
easy to lose among the successful removals:

```text
Volume vc-lead-research-v3_runtime-config  Resource is still in use
Volume vc-lead-research-v3_openclaw-state  Resource is still in use
Volume vc-lead-research-v3_vc-quarantine   Resource is still in use
```

Afterwards `docker compose ps` reports nothing, so the operator sees an empty
stack over retained data. The database is gone but `openclaw-state` is not, and
that is the tier holding inbound media and document snapshots. Name the profile:

```sh
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
  --profile tools down --volumes --remove-orphans
# The two volume names below are operator-settable, so read them from .env —
# but read them scoped. `set -a; . ./.env` would export every deployment
# secret into this shell and into every process it starts, including the
# credentials this procedure is about to decommission. Deliberately not
# reusing the Compose variable names either, so nothing can steer a later
# `docker compose` invocation in the same shell.
runtime_config_volume="$(sed -n 's/^OPENCLAW_RUNTIME_CONFIG_VOLUME=//p' .env | head -n 1)"
quarantine_volume="$(sed -n 's/^VC_QUARANTINE_VOLUME=//p' .env | head -n 1)"
docker volume ls --quiet --filter name=vc-lead-research-v3 \
  --filter name="${runtime_config_volume:-vc-lead-research-v3_runtime-config}" \
  --filter name="${quarantine_volume:-vc-lead-research-v3_vc-quarantine}"
# must return nothing. `--quiet` is what makes that literally true: without it
# `docker volume ls` always prints its `DRIVER  VOLUME NAME` header, so an
# operator testing for empty output would read a fully decommissioned stack as
# a failure. Run this before deleting .env below, or the two
# overridable names are no longer available to substitute.
```

Then remove the host-side runtime files, which no Compose command owns:
`.env`, `deployment-lock.json`, `config/customization-profile.json`,
`config/connectors.json` (if present), `config/runtime/openclaw.json`,
`config/runtime/secrets/`, and any operator payload under `inbox/` and
`quarantine/`. Retain `BACKUP_HMAC_KEY` for as long as any recovery point
written with it must stay restorable, and destroy it deliberately afterwards —
without it those archives are permanently unrestorable.
