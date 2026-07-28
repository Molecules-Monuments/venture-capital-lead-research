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
node-owned mode-`0400` file. It also copies the approval seed only when state
has no approval file, checks its exact allowlist, and leaves the resulting
mode-`0600` file writable for upstream socket-token maintenance. Gateway and
CLI run non-root with all capabilities dropped, mount the runtime-config volume
read-only, and select `/home/node/.openclaw-config/openclaw.json` with
`OPENCLAW_CONFIG_PATH`. Do not add host workspace or state-path config bind
mounts, or grant the file-backed Compose config to long-running services.

Compose applies explicit CPU, memory, PID, tmpfs, and local json-file rotation
bounds. Treat their `.env` values as capacity gates: load-test before raising
them and investigate OOM/restart evidence rather than disabling the bounds.

Bootstrap and every update take the package-wide lifecycle lock and run `scripts/rotate_runtime_role.sh`. The script takes its database-rotation lock, copies `.env` once into a mode-`0600` private snapshot, stops all declared database-secret consumers, and force-recreates Postgres so its file-backed Compose secrets are re-read. It temporarily sets the runtime role to `NOLOGIN`, evicts existing owner/runtime sessions, changes both credentials through `psql`'s protected `\password` path, removes role memberships in both directions, resets role settings, and reasserts `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`, `NOREPLICATION`, and `NOBYPASSRLS` before restoring login.

The reconciler proves both new credentials over TCP and proves that an invalid password is rejected, then force-recreates the gateway and stopped CLI container. Final `vcops db-check` probes run from both consumer images. Any failure after rotation starts stops the gateway and CLI. Changing either database password without this complete reconciliation is not a valid rotation. Do not run long-lived Compose one-offs or independent backend clients during this maintenance operation; runtime sessions are deliberately terminated. If a host crash leaves `/tmp/openclaw-lead-research-v3-rotation.lock`, confirm that no rotation process is active before removing the stale lock and retrying.

Both database passwords must be independent 24-128 character base64url-safe values (`A-Z`, `a-z`, `0-9`, `_`, `-`); this keeps Compose, `psql`, passfiles, and recovery handling unambiguous. This package requires Docker Compose, not `docker stack deploy`: its file-backed secret sources are Compose-only. `docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env config --quiet` is a mandatory compatibility preflight and the lifecycle commands require support for `up --wait`, `--force-recreate`, `--no-deps`, `--no-start`, and `run --rm`.

Backup, restore, update, bootstrap, and direct role rotation share `/tmp/openclaw-lead-research-v3-lifecycle.lock`. Nested update/bootstrap operations pass a private owner token that is checked against the mode-`0700` lock directory; setting a boolean environment flag cannot bypass the lock. If a host crash leaves the directory, confirm no lifecycle process is active before removing it. Every script pins both the absolute Compose file and project name, so invoking it from a different current directory cannot select another stack.

## Health

- `/healthz` is liveness only.
- `/readyz` is readiness and is used by Compose.
- `docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env ps` must show Postgres and the gateway healthy before workflows are accepted.
- Task Flow rows in `queued`, `running`, `waiting`, or `blocked` must be inspected during incidents; cancellation is sticky and revisions must be honored.

## Backup

Run `scripts/backup.sh <new-directory>` while the stack is healthy. The parent must already exist, the named destination must not exist, and the canonical destination must not equal, contain, or sit beneath the package `inbox/`; keep recovery points outside every live tree they capture or replace. The script takes the lifecycle lock, records whether the gateway was running, verifies that the Docker image IDs still match the deployment lock and that both pinned upstream digests are present, stops both gateway and CLI state consumers, proves Postgres readiness, and captures one named recovery window. A normal backup waits for and database-checks the gateway before publishing the result; an update deliberately keeps consumers stopped until the new release passes health checks.

The recovery point contains a custom-format Postgres dump (including preference
state and forget markers); OpenClaw state including sessions, inbound media,
Task Flow SQLite, and Lobster continuations; read-only operator inbox originals;
the named quarantine volume; a database-derived local-artifact URI/hash
inventory; package version; deployment/image/release lock; format-3 manifest;
checksums; and `BACKUP_AUTHENTICATION`. Backup verifies each database artifact
against staged bytes and authenticates the exact checksum manifest with
HMAC-SHA-256 before atomic publication.

Generated `openclaw.json`, persistent `exec-approvals.json`, volatile `exec-approvals.sock`, `.env`, database secret files, and provider/channel credentials are intentionally excluded. The target's reviewed approval seed is validated/recreated before the restored gateway starts. The state archive can nevertheless contain sessions and Lobster continuation material and the database dump contains business data: protect the entire backup as restricted operational data.

The package's recovery algorithms and tamper tests are release evidence. A live
isolated-host restore remains environment-specific commissioning evidence and
was explicitly excluded from this package-readiness effort.

## Update

1. Review upstream release notes and migration requirements.
2. Change pinned references only in a reviewed release revision; never use `latest` or `main`.
3. Preserve the deployed revision's runtime `deployment-lock.json` when placing the new package revision, then run `scripts/update.sh <new-pre-update-backup-directory>`. The update-only compatible-backup mode validates the old lock against the still-live image IDs and writes both backup `VERSION` and `BACKUP_MANIFEST.package_version` from that lock, never from the newly placed package. The old lock and its matching old version are therefore embedded together in the pre-update recovery point. The script holds one lifecycle lock from that quiesced point through build, migration, secret/role reconciliation, readiness, and recording the new lock. Do not set `OPENCLAW_BACKUP_COMPATIBLE_LOCK` manually; backup rejects it unless the private update lock and quiesced mode are both active.
4. Run all offline and live release gates again.
5. Record immutable image IDs/digests in `deployment-lock.json` using `scripts/record_images.py`.

## Rollback and restore

`scripts/restore.sh <backup-directory> --confirm-destructive-restore` is destructive. Prepare an isolated target with the exact package revision first: verify its external provenance and embedded inventory, create and validate `.env` with `PRIMARY_CHANNEL=none` and the matching retained backup HMAC key, run `scripts/bootstrap.sh` (or equivalently load/build the exact derived CLI image, start a healthy package Postgres service, initialize state, and run `scripts/record_images.py`), and retain its local `deployment-lock.json`. Only then run restore. The canonical backup source and private validation staging must not equal, contain, or sit beneath the package `inbox/`; the script rejects that overlap before mutation so replacing the inbox cannot delete the recovery point or its staged source. Before any verification it copies every backup member into private staging with a single read of each; the operator-writable backup directory is never read again after that point. It then authenticates the staged checksum manifest with HMAC-SHA-256 and verifies every staged member's checksum against that authenticated manifest, so the bytes that were authenticated are exactly the bytes that get restored — there is no verify-then-reread window. From the staged copies it validates the checksum inventory, package version, both deployment locks against the exact manifest/upstream/image-reference/migration contract, and the target's live Docker image IDs and pinned upstream digests against its local lock; structurally rejects archive traversal, links, devices, control-character or duplicate paths, sparse files, and configured entry/size/expansion-limit violations; safely extracts every state/artifact archive into private staging (removing each staged archive after extraction to bound peak staging space); restores the database dump into a disposable validation database; and proves its database artifact inventory resolves to the staged inbox/quarantine bytes. Production replacement — including the destructive `pg_restore` — streams only from that validated staging tree, never from the operator-writable original archive. Staging therefore needs temporary space for a full copy of the backup. Only then does it stop every state consumer, recreate the production database, replace OpenClaw state, inbox, and named quarantine content, reject any migration ledger row unknown to this package, apply pending migrations plus their checksums in transactions, reconcile roles, recreate secret consumers, wait for readiness, and run database checks from both images.

Run restore only in an approved maintenance window with a second current backup and a matching reviewed package. Migration runners serialize on a PostgreSQL transaction-scoped advisory lock and make their ledger decision under that lock; application and checksum registration commit together. If a failure occurs after mutation begins, the script leaves gateway and CLI stopped; do not manually start a partial system. Repair or retry the verified recovery point. Script success proves the package path, not the specific target environment; deployment commissioning may additionally exercise `doctor`, Task Flow audit, exact-once Lobster resume/cancel, models, and a selected channel.

For an image-only rollback, restore the previously reviewed image reference and package revision together. Never run an older binary against a newer schema unless the release notes explicitly state backward compatibility.

## Secrets

Keep `.env` outside version control and restrict it to the deployment operator.
Rotate gateway, model/search, trusted-context, provider, and channel secrets
after suspected exposure.

Editing `.env` is not enough, and `docker compose restart` re-reads nothing:
`OPENCLAW_GATEWAY_TOKEN` is baked into the service environment at container
creation, and the four files under `config/runtime/secrets/` are only rewritten
by a lifecycle render. The complete sequence for the non-database secrets is:

```sh
./scripts/check_env.sh .env
python3 -B scripts/render_channel_config.py .env
docker compose -f docker-compose.yml -p openclaw-lead-research-v3 \
  --env-file .env up -d --force-recreate
```

A trusted-context rotation invalidates outstanding capabilities; after the
force-recreate, prove a new document/preference operation. Note that rotating
`VCOPS_APPROVAL_PEPPER` also invalidates every approval that has not yet been
consumed — `pending` *and* `approved`-but-unconsumed alike, because the pepper
HMACs the approval token and rotation changes every stored digest. Issue those
again after rotation.
Rotate both database values together through `scripts/rotate_runtime_role.sh`.
The Teams profile withholds Graph permissions, `sharePointSiteId`, delegated
auth, and SSO. All profiles disable config writes, chat exec approvals,
administrative commands, and action tools while permitting governed
PDF/PPTX/XLSX/CSV intake. Unsupported media is blocked before model input.
