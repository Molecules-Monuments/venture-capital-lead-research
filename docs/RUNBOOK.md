# Installation and Release Runbook — Version 3.0

## 1. Release contract

Install the complete directory as one immutable revision. The supported pins
are OpenClaw `2026.7.1`, Lobster `2026.6.11`, Postgres
`17.10-bookworm`, and package version `3.0.0`. The shipped image references
also pin the reviewed multi-architecture manifest digests. Do not substitute
`latest`, `main`, a tag without its recorded digest, floating package ranges,
or a partially copied workspace.

The package is production-ready within `PRODUCTION_READINESS.md`'s defined
scope. A concrete deployment is not activatable until `CUSTOMIZATION.md` is completed and
`config/customization-profile.json` passes the customization validator. The
sample thesis, rubric, sources, retention, models, and approvers are not
universal defaults.

The release has three separate decisions:

- **Package production readiness:** the complete code, reference database
  scale, exact built image, recovery algorithms, and retained evidence pass.
- **Deployment configuration:** organization/jurisdiction policy, secrets,
  destination IDs, and models belong to the operator's environment.
- **Live commissioning:** provider accounts, a destructive recovery exercise,
  and target-host capacity are proven under real conditions when required.

Package readiness never fabricates deployment evidence. Keep
`PRIMARY_CHANNEL=none`, cron disabled, and external production traffic blocked
until the chosen deployment's applicable commissioning items pass.
Install the complete hash-locked `requirements-dev.lock` into a disposable
virtual environment (Python **3.11 or newer** — the lock is compiled for
3.11+, and `--require-hashes` refuses the unhashed backports older
interpreters need), then run that virtualenv's interpreter — activate it, or
call it by path — as `python -B scripts/verify_offline.py`, the single
deterministic entry point. Running the gate with the system interpreter instead
fails most suites with import errors, because the pinned test dependencies live
only in the virtualenv. The complete package-release proof adds
`--with-g4-database`, `--with-schema-reference`, `--with-retrieval-scale`, and
`--with-g6-image <built-image>` when local PostgreSQL 17 and Docker are
available. Live deployment
evidence (G8) is collected separately with `--with-deployment` against a
commissioned environment, as `PRODUCTION_READINESS.md` specifies; offline runs
never substitute for it.

## 2. Host prerequisites

Use a dedicated Linux host inside one organizational trust boundary. Require:

- Docker Engine **24.0 or newer with the Compose v2 plugin 2.20 or newer**
  (`docker compose version`). Compose v1 (`docker-compose`) is not supported.
  The stack needs `up --wait`, `--force-recreate`, `--no-deps`, `--no-start`,
  file-backed Compose secrets, Compose configs,
  `service_completed_successfully`, and profiles; a distribution's older
  `docker.io`/`docker-compose` packages typically lack several of these and
  fail at the first `docker compose ... config --quiet`. Secret files are
  materialized from `.env` into `config/runtime/secrets/` by
  `scripts/render_channel_config.py` on every lifecycle path (mode-`0444`
  files inside a mode-`0700` directory — the unprivileged container users must
  read the bind-mounted files, so confidentiality comes from the directory
  boundary, matching `.env`; the directory is ignored by git and the release
  manifest) — environment-backed secrets cannot be injected into
  read-only services;
- sufficient durable storage for Postgres (including scoped user preferences),
  OpenClaw/Task Flow/Lobster state, inbound document snapshots, quarantine,
  backups, and expected retention;
- working DNS, UTC-synchronized time, outbound TLS to the selected model
  provider, optional search/fetch providers, image/package registries, approved
  research endpoints, and only the selected channel provider;
- loopback or private access to the gateway; a hardened TLS reverse proxy that
  exposes only `/api/messages` if Teams is selected; and
- a POSIX shell plus host `python3` **3.9 or newer** — the lifecycle scripts
  `bootstrap.sh`, `update.sh`, `backup.sh`, `restore.sh`, and
  `rotate_runtime_role.sh` shell out to it, and `check_customization.py`
  imports `zoneinfo`, which is 3.9+ (`migrate.sh` needs no python3; it uses
  POSIX utilities — `awk`, `sed`, `grep`, `cmp`, `command`, and
  `sha256sum`/`shasum`). The backup and restore paths additionally call `tar`,
  `mktemp`, `tr`, `cut`, `head`, `stat` and `chmod`, all present in a normal
  distribution base install — check them explicitly if you build a minimal
  recovery host for the §5.4 drill;
- `openssl`, used to generate the six deployment secrets; and
- a non-root deployment operator with exclusive control of the package and
  `.env`.

Do not mount the Docker socket, enable privileged mode, publish Postgres, expose
the Control UI publicly, or share this gateway across hostile trust domains.

## 3. Prepare the release

From the package root:

```sh
cp .env.example .env
chmod 0600 .env
```

Generate independent high-entropy values for all six secrets: the gateway
token, Postgres owner password, Postgres runtime password, approval pepper,
trusted-context HMAC key (`VC_TRUSTED_CONTEXT_KEY`), and backup HMAC key. The
trusted-context and backup keys must each be 64 hexadecimal characters
(`openssl rand -hex 32`) and must not be reused for any other purpose; the
backup key must additionally be transferred/retained independently of recovery
points.
Database passwords
must satisfy the validator's 24–128 character base64url-safe contract and must
not equal one another. Populate the model credential. Leave every channel
family blank and keep:

```text
PRIMARY_CHANNEL=none
OPENCLAW_HOST=127.0.0.1
MSTEAMS_WEBHOOK_HOST=127.0.0.1
```

Validate and render:

```sh
./scripts/check_env.sh .env
python3 -B scripts/render_channel_config.py .env
docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env config --quiet
```

Any validation error, missing or unknown value, ambient Compose
steering/override, extra unselected channel credential, symlinked environment
file, non-`0600` environment/runtime config, non-loopback host binding, or
invalid resource/log bound is a failure. The validator's identical-model-ID
warning is allowed only when that deliberate choice and its benchmark are
recorded in the customization profile. Never edit
`config/runtime/openclaw.json` directly. The host file remains mode `0600`;
only the one-shot `openclaw-state-init` service receives it as a Compose config.
That networkless, read-only-root service validates the document and atomically
copies it into the dedicated `OPENCLAW_RUNTIME_CONFIG_VOLUME` with owner
`node:node` and mode `0400`. Gateway and CLI mount that volume read-only and
select `/home/node/.openclaw-config/openclaw.json` through the upstream-supported
`OPENCLAW_CONFIG_PATH` variable. This avoids relying on ignored Compose
config `uid`, `gid`, or `mode` attributes for file-backed sources.

Before deployment, verify the package's internal inventory against its embedded
`manifest.json`:

```sh
python3 -B scripts/verify_release.py --pristine
```

`--pristine` rejects undeclared caches, editor/OS debris, symlinks, and special
files as well as changed declared files. It stays correct after installation and
during normal operation, so prefer it always: `.env`,
`config/customization-profile.json`, `config/connectors.json`, the rendered
runtime config and secrets under `config/runtime/`, and `deployment-lock.json`
are all on the verifier's allowed-runtime list, and operator payload inside `./inbox` and `./quarantine` is
tolerated because those are operator working directories rather than package
content (`./inbox` is the optional operator-only manual drop point, not the
channel attachment path; `./quarantine` is a runtime
quarantine placeholder — the deployed stack quarantines rejected uploads into
the `vc-quarantine` named volume, not into this directory). A
*symlink* in either of those directories is still reported — the gateway would
follow it out of the intended tree. This is a
self-consistency check, not an external authenticity root: first verify the
trusted distribution signature or out-of-band package digest. A mismatch means
the directory is not internally consistent with its embedded inventory. It is
also deliberately offline and makes no claim about locally installed Docker
images; bootstrap, backup, and restore use `record_images.py`'s separate live
validation to bind those image IDs and pinned upstream digests.

## 4. Fresh installation

Create the reviewed `config/customization-profile.json` first (complete
`CUSTOMIZATION.md` and the README "Customize, install, and commission" step 1);
bootstrap refuses the shipped publication example until the profile passes
`scripts/check_customization.py` against the prepared `.env`. Then run:

```sh
./scripts/bootstrap.sh
```

Bootstrap validates the environment, renders the inert config, validates
Compose, pulls pinned Postgres, builds the derived OpenClaw image, reconciles
both database credentials and the restricted runtime role, applies append-only
migrations, recreates secret-consuming containers, and waits for readiness.
Migration application and immutable checksum registration occur in one database
transaction under a transaction-scoped advisory lock. A concurrent migrator
waits, re-reads the ledger under that lock, and either validates/skips or applies
and registers; the ledger rejects a changed name or SHA-256 at an existing
version. Only `migrations/000_roles.sh` is mounted into Postgres initialization;
numbered application migrations are streamed exactly once by `migrate.sh`.

`bootstrap.sh` already records the immutable image IDs and pinned upstream
digests into `deployment-lock.json` as its final step, so no separate command is
required. Retain the complete command transcript; to re-affirm or re-print the
recorded lock independently you may re-run the same recorder:

```sh
python3 -B scripts/record_images.py
```

Do not proceed if the image build, package-version assertion, database password
proof, negative invalid-password proof, role restriction check, migration,
consumer `vcops db-check`, or `/readyz` fails.

The derived image installs the `runtime-packages/package-lock.json` graph with
`npm ci`, installs Python requirements with hash verification, and bakes the
reviewed `/workspaces` tree read-only. Before the gateway starts, the one-shot
`openclaw-state-init` service copies and validates the rendered config as
described above. It also copies the reviewed exec-approval seed into the
writable state volume only when absent, forces mode `0600`, and verifies the
two exact data-steward executable paths. The initializer runs as root with all
capabilities dropped except `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`; it has no
network and exits before the gateway starts. Gateway and CLI remain non-root,
drop all capabilities, and gain no added capability. OpenClaw may maintain its
own socket token in the writable approval file.

## 5. Deployment commissioning checklist

This section covers the live provider/recovery and target-runtime work that was
explicitly excluded from the Version 3.0 package-readiness decision. Apply only
the rows relevant to the deployment being commissioned. These checks govern
activation of that environment; their exclusion does not change the package's
production-ready status.

Create an evidence directory outside the package and retain timestamps, command
versions, exit codes, redacted JSON, config/manifest/image digests, and database
counts. Secrets and approval tokens must never appear in evidence.

### 5.0 What the shipped gates already prove

Most rows below do not have to be proven by hand. The package ships gates that
already establish them; run the gate, keep its JSON output as the evidence for
those rows, and spend your effort on the rest. Nothing here lowers the bar —
it only stops you re-deriving what the package already demonstrates.

| Rows | Already proven by | What is still yours |
| --- | --- | --- |
| 5.1 OpenClaw/Lobster/channel/search/Python/Debian versions; per-profile config validation; skill-workshop hook | `verify_offline.py --with-g6-image <image>` | Record *your* live image IDs: `python3 -B scripts/record_images.py --validate-live deployment-lock.json` |
| 5.1 agent authority boundary (no direct Lobster, exec, config, cron, gateway or DB authority) | `validate_skill_system.py` and the `tests/infrastructure` exec-allowlist contract, both inside `verify_offline.py` | — |
| 5.1 rendered-config mode, ownership, digest and read-only mounting | `tests/infrastructure` plus the in-container initializer assertions exercised by `run_g8_deployment.py` | — |
| 5.1 `/healthz` and `/readyz` behaviour; private-path reachability | — | Yours: depends on your host and proxy |
| 5.2 migration names, checksums, and no-op replay | `verify_offline.py --with-g4-database` (applies and registers every migration twice) | Inspect `schema_migrations` once on your database |
| 5.2 `openclaw_runtime` is `NOINHERIT`, non-superuser, non-replication, cannot create databases/roles/schema/temp objects, no role membership | `tests/g4/test_database_contract.py` asserts that exact privilege set | — |
| 5.2 typed lifecycle, idempotent replay, optimistic conflict, approval consume/replay denial, notification claim/retry, cross-lead document provenance | the same G4 gate | — |
| 5.3 all eighteen workflows parse, reject shell injection, environment leaks and unsafe authority | `validate_workflows.py` and `tests/g5` | — |
| 5.3 live workflow execution | `run_g8_deployment.py` live-runs six workflows end-to-end through real `vcrun`/Lobster | Live-run the remaining twelve against your deployment |
| 5.3 routing matches the retained fixtures | **nothing — no in-package executor** | Yours, and it needs human judgement (see below) |
| 5.4 backup/restore argument contracts, archive bounds, HMAC tampering refusal | `tests/g7` | The actual backup, and the restore drill — **never executed by any gate** |
| 5.5 all five channel schemas validate; the `none` profile connects no provider | `verify_offline.py --with-g6-image` and `run_g8_deployment.py` | The channel matrix in `docs/CHANNELS.md`, if you enable one |

So the work that genuinely remains is: your live image IDs, your health endpoints,
your restart-survival and restore drill, your credential rotation, live-running
the remaining workflows, and judging model output quality.

### 5.0.1 Which rows apply

Every feature is available by configuration. None is reserved for a particular
size of organization, and no row below is waived by running a small deployment
— what varies is only how many rows are in scope for what you enabled.

The channel matrix in `docs/CHANNELS.md` is twelve mechanical rows exercised
against a running deployment: allowed and unknown senders, preference isolation
between two users, a supported and an unsupported attachment, a restart
mid-conversation, and rollback to `none`. It is keyboard work, not a document
exercise.

The twenty review flags in the customization profile are attestations. This
package neither makes nor evaluates them: `check_customization.py` refuses the
profile until each is `true`, and the deployment does not start. Whether any
given statement holds for your organization, jurisdiction, data and model
choice is outside this software's scope and is yours to determine.

The restore drill in §5.4 is the one item no gate covers.

### 5.1 Image and configuration

- Prove the runtime OpenClaw version is exactly `2026.7.1` and record the image
  digest/ID.
- Prove Lobster resolves from `/opt/openclaw-runtime` at exact `2026.6.11`,
  Slack, Teams, and Discord resolve from the locked runtime graph at exact
  `2026.7.1`, and bundled Telegram is exact `2026.7.1`.
- Run the pinned OpenClaw configuration validation, `doctor`, secret audit, and
  deep security audit inside the exact image.
- Prove the host rendered config is a non-symlink regular file at mode `0600`;
  the initializer's named-volume copy has the same SHA-256, owner `node:node`,
  and mode `0400`; and gateway and CLI mount that volume read-only without a
  direct Compose-config grant or added capabilities.
- Prove `/healthz` and `/readyz` have their distinct liveness/readiness
  behavior and that the gateway/Control UI is reachable only through the
  intended private path.
- Prove no agent has direct Lobster, arbitrary exec, configuration, cron,
  message, gateway, or database-secret authority beyond the reviewed boundary.
- Prove only `vc-chief` receives `skill_workshop`; create/update/revise/list/
  inspect remain available, while apply/reject/quarantine, an unknown action,
  and a non-chief caller are blocked by the image-owned hook.

### 5.2 Database and helper

- Run `db-check` from both consumer images. There is no `vcops` on `PATH`;
  use the absolute wrapper, and override the CLI service's own entrypoint:

  ```sh
  docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
    exec openclaw-gateway /workspaces/vc-chief/vc/bin/agent/vcops db-check
  docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
    --profile tools run --rm --no-deps \
    --entrypoint /workspaces/vc-chief/vc/bin/agent/vcops openclaw-cli db-check
  ```
- Inspect `schema_migrations`; prove every migration name and external SHA-256
  matches the release and a repeat run is a no-op.
- Prove `openclaw_runtime` is `NOINHERIT`, non-superuser, non-replication,
  cannot create databases/roles/schema/temp objects, and has no role membership
  in either direction.
- Exercise one typed create/read/update lifecycle, idempotent replay, optimistic
  conflict, approval consume/replay denial, notification claim/retry/receipt,
  and cross-lead document-provenance case.
- Run the retained G4 suites using the locked dependency versions.

### 5.3 Agents, workflows, Task Flow, and Lobster

- Start a fresh session for every role and prove routing matches the retained
  fixtures; untrusted instructions and prohibited side effects must be denied.
- Dry-run and live-run all eighteen fixed workflows with exact inputs. Each must
  reach the correct Postgres terminal state exactly once.
- Prove `document-ingest` and `document-lead-intake` bind a supported channel
  file to the authenticated principal and content-addressed snapshot. Prove
  `preference-observe` and `preference-forget` cannot cross user, account, or
  channel scope and reject group-sourced writes.
- Prove arbitrary selector/path/pipeline/cwd/environment/extra arguments fail
  before Lobster invocation and output remains bounded/redacted.
- Pause `evaluate-lead`, restart the gateway, resume once through the
  authenticated operator-only path, and prove a second resume fails.
- Reject/cancel once; prove Lobster state is removed, Postgres is `cancelled`,
  and any mirrored Task Flow is cancelled rather than reported succeeded.
- Force a Postgres record-version and Task Flow revision conflict; both must
  fail without overwriting newer state.
- Run the Task Flow audit and maintenance commands. `openclaw` is not
  installed on the host; it lives in the gateway image:

  ```sh
  docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw tasks audit
  docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw tasks maintenance
  ```

  Unresolved broken/stale records are failures. Every other bare `openclaw …`
  command in this runbook runs the same way.

### 5.4 Persistence and disaster recovery

Backups are bounded, and the bounds are not advisory: `backup.sh` validates each
archive with `--max-entries 100000`, `--max-member-bytes 2 GiB`, `--max-ratio
500`, and a per-class total — 2 GiB for the `state` tier (raise it with
`OPENCLAW_STATE_ARCHIVE_MAX_BYTES` in `.env`, up to 100 GiB) and a fixed 20 GiB
for `inbox` and `quarantine`. Document snapshots and extractions accumulate in
the `state` tier, so a deployment with sustained attachment intake will reach
that bound; raise it and size the volume before backups begin failing. The
entry-count, member-size and ratio bounds have no configuration escape.

- Restart and recreate every service and prove sessions, Task Flow SQLite,
  Lobster continuation, Postgres business data and preferences, runtime config,
  inbound document snapshots, and quarantine survive. Record the resolved
  stable named-volume names before
  the drill and prove a newly rendered config replaces the runtime copy only
  through a successful initializer run.
- Run `./scripts/backup.sh <new-directory>` whose parent exists, whose final
  path does not, and whose canonical path does not overlap the package inbox.
  Prove gateway and CLI were quiesced; the final directory was published only
  after all checks; and normal service readiness was restored.
- Verify `BACKUP_AUTHENTICATION`, `SHA256SUMS`, `BACKUP_MANIFEST`, and
  `LOCAL_ARTIFACTS.tsv`. Prove the dedicated external HMAC key authenticates
  the exact checksum manifest before any member checksum is trusted. Prove the
  recovery point includes Postgres (including preferences), OpenClaw/Task
  Flow/Lobster state, read-only inbox originals, inbound document snapshots,
  and the named quarantine volume while
  excluding `.env`, generated runtime config, exec approvals, and secrets.
- On the isolated target, verify the exact package, prepare a valid inert
  `.env`, and prepare a customization profile **for that host**: both
  `bootstrap.sh` and `restore.sh` validate the profile against the `.env`
  before doing anything, and the profile is deliberately not inside the backup.
  Copy your reviewed policy artifacts and `config/customization-profile.json`
  across, set `channels.selected` to `none` and `approvals.allowed_channel_ids`
  to `[]` so they match the inert `.env`, keep `organization.timezone`,
  `models.*` and `search.*` byte-identical to that `.env`, re-pin with
  `python3 -B scripts/init_customization.py --update-hashes`, and confirm
  `python3 -B scripts/check_customization.py config/customization-profile.json .env`
  passes. A production profile that selects a channel will not validate here. That `.env` **must carry the same `BACKUP_HMAC_KEY` that was in force
  when the backup was written** — `restore.sh` authenticates the checksum
  manifest with it and aborts with "backup authenticity verification failed"
  otherwise. A fresh key on the recovery host makes every existing recovery
  point unrestorable, so treat the key as part of the recovery point and store
  it independently of the archives. Then run `./scripts/bootstrap.sh` so the
  derived CLI image, healthy Postgres,
  initialized volumes, and local `deployment-lock.json` exist. Then restore the
  matching backup from a canonical path outside the package inbox with
  `./scripts/restore.sh <directory> --confirm-destructive-restore`.
- Retain the successful live-lock evidence showing that the target image IDs
  match its deployment lock and the OpenClaw/Postgres RepoDigests contain the
  exact pinned digests. This is distinct from the offline manifest check.
- Retain evidence that archive/path/hash validation and a disposable database
  restore completed before production mutation, every local database artifact
  URI resolved to matching staged bytes, and a forced mid-restore failure left
  all state consumers stopped.
- Re-run database/migration checksums, restricted-role checks, `doctor`, Task
  Flow error audit, Lobster exact-once resume and sticky cancel, state
  persistence, readiness, model, and applicable channel checks against the
  restored system. A backup without this clean-target restore drill is not a
  passing backup.
- Rotate the gateway token, database owner/runtime credentials, approval pepper,
  trusted-context HMAC key, backup HMAC key, and selected channel/model/search
  credentials; prove old credentials fail and new credentials work without
  duplicate consumers. The two database credentials rotate together through
  `./scripts/rotate_runtime_role.sh`. The script does not invent credentials: it
  reads both passwords out of `.env`, so write the new values there first
  (24–128 base64url-safe characters each, and different from one another), then
  run it. Running it without changing `.env` reconciles the role and reports
  success while rotating nothing. Never change `.env` alone either — the script
  is what re-reads the file-backed secrets and reconciles the role. The other
  secrets need a re-render and a force-recreate, not a restart — see
  `docs/OPERATIONS.md` "Secrets" for the exact sequence. Rotating
  `VCOPS_APPROVAL_PEPPER` invalidates every approval not yet consumed —
  `pending` *and* `approved`-but-unconsumed — because the pepper HMACs the
  approval token and rotation changes every stored digest; re-issue them
  afterwards.

### 5.5 Channel

If no external channel is required, retain `PRIMARY_CHANNEL=none` and prove no
provider is enabled or connected. If a channel is required, follow
`docs/CHANNELS.md` and pass every row for exactly one of Slack, Teams, Discord,
or Telegram. The other three credential families must be empty. An attachment
matrix must prove supported documents are routed through the deterministic
inspection/extraction lane, while unsupported media and unsafe documents are
rejected before model exposure and before any business-data mutation.

After the selected matrix passes, roll back to `none`, prove disconnection, and
then re-enable only the reviewed profile. This rollback proof is part of G8.

### 5.6 Commissioning decision

The deployment is commissioned only when every applicable item above and every row of the selected
channel matrix is `PASS`, with evidence. `NOT RUN`, missing evidence, warnings,
manual exceptions, partial provider matrices, and “works in principle” are
not commissioning evidence. Cron and unattended execution stay disabled until
the environment-specific decision is recorded.

## 6. Channel activation

Collect only stable provider IDs and populate one credential family. Set
`PRIMARY_CHANNEL` to `slack`, `msteams`, `discord`, or `telegram`, and update
the reviewed `config/customization-profile.json` in the same change: its
`channels.selected` must equal the new `PRIMARY_CHANNEL`, its
`approvals.allowed_channel_ids` must exactly match the selected destination
IDs from `.env`, and the change record must note the review — otherwise the
next lifecycle validation fails closed on the profile/environment mismatch.
Then rerun:

```sh
./scripts/check_env.sh .env
python3 -B scripts/check_customization.py config/customization-profile.json .env
python3 -B scripts/render_channel_config.py .env
docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env config --quiet
docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env run --rm --no-deps openclaw-state-init
docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env up -d --wait --force-recreate --no-deps openclaw-gateway
```

The `openclaw-state-init` run is required, not optional: the gateway reads the
rendered config from the runtime-config volume, and that one-shot service is the
only writer of it. Recreating the gateway alone leaves the previous channel
config mounted. Re-running `./scripts/bootstrap.sh` does the same thing.

The `check_customization.py` step is what makes the profile/environment mismatch
fail closed here (and on every `update`/`restore`/`rotate` path), before the
re-rendered config reaches the gateway.

Teams additionally requires a public HTTPS URL ending in `/api/messages` while
the host port remains loopback-bound. Expose no other gateway path. Discord
requires Message Content intent but not Server Members/Presence for the ID-only
profile. Telegram uses one long poller per token. Slack uses one Socket Mode app
per gateway. All four profiles accept only commissioned PDF, PPTX, XLSX, and CSV
documents within the configured byte limit; unsupported media and remote
administrative/approval surfaces remain blocked. Teams channel/group files need
a separately commissioned Microsoft Graph/SharePoint path; Teams personal/DM
attachments are the supported baseline.

## 7. Routine operation

Daily:

- inspect readiness, service restarts, channel status, failed/held notification
  counts, active workflow age, and disk capacity;
- investigate provider retries by stable event ID before retrying a domain
  effect; and
- keep public research and generated text classified as untrusted input.

Weekly or after incidents:

- run Task Flow audit/maintenance, the OpenClaw secret/deep-security checks, and
  a manifest/config/image-digest comparison;
- review pending/expired approvals, stale notification claims, unresolved
  contradictions, pending governance and skill proposals (decisions on
  captured proposals are recorded through the operator-gated
  `proposal-decide` helper command, never a direct database update — see
  "Operator administration lane" in `OPERATIONS.md` for the runnable form),
  quarantine retention, and access logs; and
- create a new backup and periodically perform an isolated restore drill.

Never call queued/attempted work delivered, infer approval from chat, resume an
unknown token, repair a checksum ledger by editing it, or blind-retry an
ambiguous external send.

## 8. Updates and rollback

Before any update, review current upstream code/release notes, create a passing
backup, produce a new reviewed package/manifest, and rerun every offline gate.

Then carry the deployed revision's runtime files into the new package directory:
`deployment-lock.json`, `.env`, `config/customization-profile.json`,
`config/connectors.json` if you use connectors, and every customized policy
artifact. A freshly built package contains none of them, and `update.sh` runs
`check_env.sh` and `check_customization.py` — which re-hashes the twenty
reviewed artifacts against the new tree — before it takes the lifecycle lock. So
re-pin afterwards:

```sh
python3 -B scripts/init_customization.py --update-hashes
python3 -B scripts/build_release_manifest.py
```

Then run:

```sh
./scripts/update.sh <new-pre-update-backup-directory>
```

The update holds a lifecycle lock, creates an atomically published recovery
point while consumers are quiesced, and keeps them stopped through the same
credential, role, migration, readiness, and consumer reconciliation. It records
new image IDs only after those checks pass. If any later step fails, consumers
remain stopped; restore the verified pre-update recovery point or repair the
reviewed release. Repeat all G8 checks affected by binary, schema,
configuration, provider, workflow, or model changes that affect the deployed
environment.

Rollback uses the prior package revision, its exact image digest, and a
compatible database/state backup together. Do not point an older binary at a
newer schema unless upstream explicitly documents compatibility. For channel
rollback, set `PRIMARY_CHANNEL=none`, clear all channel fields, validate/render,
force-recreate the gateway, and prove disconnection.

### 8.1 Promote a pending skill candidate

A Workshop proposal is not an installed skill. Do not run Workshop `apply` in
the live deployment: that would bypass the package's explicit agent skill list,
resolver, schemas, fixtures, read-only image ownership, manifest, and rollback
process.

For an accepted pending proposal:

1. Inspect the exact proposal ID through the authenticated operator UI or
   `openclaw skills workshop inspect <proposal-id> --json`; record its draft
   hash and scan result without copying secrets or deal data into release
   evidence.
2. Add the rendered `SKILL.md` and reviewed support files to
   `workspaces/shared-skills/<skill-name>/` in a new repository revision.
3. Update `config/openclaw.json`, the owning agent's `AGENTS.md` and `TOOLS.md`,
   `workspaces/vc-chief/vc/RESOLVER.md`, any canonical schemas/helpers/workflows,
   public documentation, and positive, negative, adversarial, and routing
   fixtures.
4. Deliberately update the exact inventory in
   `scripts/validate_skill_system.py`; an unexplained count change is a release
   failure.
5. Run the official `skill-creator` `quick_validate.py` against the new skill
   (an external upstream tool, not shipped in this package — obtain it from
   the reviewed skill-creator distribution), then run
   `python3 -B scripts/validate_skill_system.py` and the complete locked
   virtual-environment gate.
6. Rebuild the image, run disposable Postgres, retrieval-scale when affected,
   and exact-image gates, then regenerate and verify the release manifest.
7. Obtain named code/security/privacy review and deploy through the normal
   update procedure. Confirm routing and rollback in commissioning.

Rejecting or quarantining a proposal is likewise an authenticated operator
lifecycle decision; an agent cannot make it. Preserve the reason and audit
record. Autonomous transcript review remains disabled.

## 9. Incident fail-closed actions

- **Credential exposure:** set the affected channel to `none`, stop consumers,
  rotate the credential, inspect audit/provider logs, and rerun its live matrix.
- **Role reconciliation failed** (`openclaw_runtime role restrictions did not
  reconcile`, or any `rotate_runtime_role.sh` failure): the script has already
  stopped the gateway and CLI, and both database passwords in `.env` may now
  differ from what Postgres holds. Do not re-run the script blindly. Confirm
  Postgres is up (`compose ps`), then check which credentials actually work by
  connecting as each role from the Postgres container; if `.env` is ahead of the
  database, the owner password in `.env` is the one to correct. Once a working
  owner credential is in `.env`, re-run the script — it is idempotent. If
  neither credential works, restore from the last verified recovery point
  (§5.4); the database is the authoritative state and the gateway is stateless
  against it.
- **Database/auth anomaly:** stop gateway and CLI, preserve evidence, run the
  locked role reconciler, and do not restore traffic until both positive and
  negative authentication proofs pass.
- **Duplicate/ambiguous same-thread reply:** disable the selected channel,
  reconcile provider event and message IDs, and never create a new idempotency
  key until the original outcome is known. There is no proactive dispatcher to
  stop in Version 3.
- **Workflow stranded:** inspect the same Task Flow and Postgres run, honor
  current revisions, cancel sticky work if required, and reconcile the existing
  run rather than starting a replacement.
- **Malicious document:** keep the original quarantined, do not open it with an
  office application, record its hash/provenance, and preserve the governed
  rejection evidence.
- **Integrity mismatch:** if the reported paths are edits you deliberately made
  — customized policy artifacts, a replaced rubric — re-pin the inventory with
  `python3 -B scripts/build_release_manifest.py` and re-run the gate. Otherwise
  stop installation/update and reacquire the reviewed release. Never regenerate
  hashes around a change you cannot account for.

## 10. Known release limitations

- The package does not provide hostile multi-tenant isolation or Docker-backed
  tool sandboxes inside the gateway container.
- Direct Lobster and managed Lobster-to-Task-Flow mode remain disabled; the
  fixed sanitized runner is the only agent workflow boundary.
- Direct-message document intake supports PDF, PPTX, XLSX, and CSV after the
  selected channel's attachment matrix passes. Images, audio, video, legacy or
  macro-enabled Office files, encrypted documents, and unsafe containers remain
  blocked. Teams channel/group files require separate Graph/SharePoint
  commissioning; personal/DM attachments are the packaged baseline.
- Provider connectivity, callbacks, polling, model calls, a target-server
  restore drill, jurisdiction-specific policy, and target-host load are
  deployment-commissioning responsibilities excluded from the package
  readiness decision.
- Cron and autonomous production execution are not enabled by this release's
  fail-closed default. Autonomous source surveillance is available as a
  deliberate four-step opt-in. (1) Set `config/openclaw.json`
  `cron.enabled: true`. (2) Because that file is a hash-pinned reviewed
  artifact, record the edit in `config/customization-profile.json` — update its
  `review.reviewed_artifacts` SHA-256 for `config/openclaw.json` and the change
  record — or the next lifecycle validation fails closed. `config/openclaw.json`
  is *also* declared in `manifest.json`, so regenerate that too
  (`python3 -B scripts/build_release_manifest.py`) or
  `verify_release.py` reports a permanent `hash mismatch` for it. (3) Re-run
  `./scripts/bootstrap.sh` so the edit actually reaches the gateway: the
  gateway reads the rendered volume copy at
  `/home/node/.openclaw-config/openclaw.json`, never the host file, so a bare
  edit does not take effect. (4) Run `./scripts/schedule_jobs.sh` to seed the
  native cron job that drives `source-scan` on a schedule (idempotent via a
  declaration key). It is a commissioning action — validate the seeded job with
  `openclaw cron list` — and never performs autonomous outreach.

## 11. Rebuilding after a Debian point release

`Dockerfile.openclaw` pins exact Debian package revisions (for example
`curl=7.88.1-10+deb12u15`) as a deliberate reproducibility contract. The
bookworm `main` pool keeps only the current revision of each package, so once
Debian ships a newer point release those exact pins are eventually removed from
`deb.debian.org` and `compose build --pull openclaw-gateway` (bootstrap/update)
fails with `has no installation candidate`. The image build wraps the `apt-get
install` step to turn that otherwise-opaque failure into an actionable message.
To recover a byte-reproducible build, point apt at a `snapshot.debian.org`
timestamp that still carries the pinned versions before building:

```sh
printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/<YYYYMMDDTHHMMSSZ>/ bookworm main\n' \
  > /etc/apt/sources.list.d/snapshot.list
```

(add it inside the build, or bake it into a local Dockerfile overlay). Choose a
timestamp at or shortly after this release's freeze date. Alternatively, run the
reviewed-release process: bump the pins in `Dockerfile.openclaw`, then re-run
every release gate (offline, disposable Postgres, retrieval-scale, exact-image,
and the real deployment gate) and regenerate the manifest before shipping. A
floating (unpinned) fallback is intentionally not used because it would break the
exact-pin reproducibility contract.
