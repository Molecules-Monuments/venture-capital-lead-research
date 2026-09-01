# Installation and Release Runbook — Version 3.0

## 1. Release contract

Install the complete directory as one immutable revision. The supported pins
are OpenClaw `2026.8.1`, Lobster `2026.6.11`, Postgres
`17.10-bookworm`, and package version `3.0.1`. The shipped image references
also pin the reviewed multi-architecture manifest digests. Do not substitute
`latest`, `main`, a tag without its recorded digest, floating package ranges,
or a partially copied workspace.

The package is production-ready within `PRODUCTION_READINESS.md`'s defined
scope. A concrete deployment is not activatable until `CUSTOMIZATION.md` is completed and
`config/customization-profile.json` passes the customization validator. The
sample thesis, rubric, sources, retention, models, and approvers are not
universal defaults.

> [!IMPORTANT]
> **One-time break at the open-source publication of this release.** Relicensing
> to Apache-2.0 and renaming the project rewrote the SPDX line and the
> project-name header at the top of all eighteen `migrations/*.sql` files, and
> renamed the Compose project and the derived image to `vc-lead-research-v3`
> and `vc-lead-research:3.0.0`. Both are byte changes, so both are breaking:
>
> - Every migration's SHA-256 moved. `scripts/migrate.sh` reconciles the file
>   digests against `schema_migrations.checksum_sha256` before it applies
>   anything, and `schema_migrations` is append-only — so on a database
>   migrated by an earlier revision, `migrate.sh` exits with `database contains
>   an unexpected or incompatible migration ledger row`, and `bootstrap.sh`,
>   `update.sh`, `rotate_runtime_role.sh` and `backup.sh` all fail with it. The
>   ledger cannot be repaired in place; §9 forbids editing it.
> - The Compose project name is what Docker derives the `postgres-data` and
>   `openclaw-state` volume names from. Under the new name Compose creates
>   empty volumes and leaves the populated ones dangling — silently, because
>   every script addresses its volumes through `docker compose -p`. The
>   `runtime-config` and `vc-quarantine` volumes are exempt only where `.env`
>   sets `OPENCLAW_RUNTIME_CONFIG_VOLUME` and `VC_QUARANTINE_VOLUME`
>   explicitly, as `.env.example` does.
> - Recovery points taken before this change record the old image reference and
>   the old migration digests in their `deployment-lock.json` member, so
>   `restore.sh` refuses them: its lock validation step runs
>   `record_images.py --validate-lock` against the recovery point's own
>   `deployment-lock.json`.
>
> There is no upgrade path across this boundary. A deployment created from an
> earlier revision must be re-bootstrapped from a fresh install and its data
> re-loaded by hand; do not attempt an in-place `update.sh`. No deployment of
> this package existed outside the development host when the change was made,
> which is why it was taken — the same reasoning
> `docs/PRODUCTION_READINESS.md` records for the pre-release migration fixes.
> Nothing after this revision may edit a migration file.

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
- **at least 2 CPUs and 4 GiB RAM**, and about 3 GB of Docker image storage
  before any data. These are floors for bootstrap to complete, not a capacity
  target. The gateway service declares `cpus: ${OPENCLAW_GATEWAY_CPU_LIMIT:-2.0}`,
  and the Docker daemon validates a container's CPU quota against the host CPU
  count at create time — on a 1-vCPU host the create fails outright, after
  `bootstrap.sh` has already begun mutating. `bootstrap.sh` also builds the
  derived image, whose `npm ci` and apt steps are OOM-killed (exit 137) on a
  host with under ~2 GiB free, and the two pinned images occupy roughly
  0.6 GB + 2.2 GB before Postgres holds a row. Size the host for the workload
  above these floors, and lower `OPENCLAW_GATEWAY_CPU_LIMIT` deliberately if
  you must run smaller;
- sufficient durable storage for Postgres (including scoped user preferences),
  OpenClaw/Task Flow/Lobster state, inbound document snapshots, quarantine,
  backups, and expected retention;
- working DNS, UTC-synchronized time, outbound TLS to the selected model
  provider, optional search/fetch providers, image/package registries, approved
  research endpoints, and only the selected channel provider. The three
  OpenClaw-owned hosts enumerated below (`telemetry.openclaw.ai`,
  `catalog.openclaw.ai`, `clawhub.ai`) do **not** belong in that allowlist:
  this release pins the first two off, so traffic to either means a pin is
  missing from the rendered config — §5.1 reads such a line as a fault, not as
  a requirement — and denying the third degrades nothing;
- loopback or private access to the gateway; a hardened TLS reverse proxy that
  exposes only `/api/messages` if Teams is selected; and
- a POSIX shell plus host `python3` **3.9 or newer** — the lifecycle scripts
  `bootstrap.sh`, `update.sh`, `backup.sh`, `restore.sh`, and
  `rotate_runtime_role.sh` shell out to it, and `check_customization.py`
  imports `zoneinfo`, which is 3.9+ (`migrate.sh` needs no python3; it uses
  POSIX utilities — `awk`, `cmp`, `command`, `dirname`, `grep`, `mktemp`, `rm`,
  `sed`, and `sha256sum`/`shasum`). Across every lifecycle script the external
  utilities are `awk`, `basename`, `cat`, `chmod`, `cmp`, `cp`, `cut`, `date`,
  `dirname`, `find`, `grep`, `head`, `mkdir`, `mktemp`, `rm`, `rmdir`, `sed`,
  `sha256sum`/`shasum`, `tar`, `tr` and `wc`
  (`tests/v3/test_doc_tree_consistency.py` fails the offline gate if a script
  starts calling one of a fixed vocabulary of common POSIX utilities that this
  list omits; a tool outside that vocabulary, or invoked through a wrapper, is
  still yours to notice). `dirname` deserves particular attention:
  it is the first external command every one of them runs, and it is the only
  one whose absence does not fail closed — the
  `PACKAGE_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"` prologue
  resolves `PACKAGE_DIR` to `/` and the script proceeds against the wrong tree,
  so the operator sees a downstream missing-file error rather than the real
  cause. All are present in a normal distribution base install, but check them
  explicitly if you build a minimal recovery host for the §5.4 drill, because
  `restore.sh` reaches `find` only *after* it has begun replacing production
  state;
- `openssl`, used to generate the six deployment secrets; and
- a non-root deployment operator with exclusive control of the package and
  `.env`.

**The three unsolicited outbound calls the harness makes on its own.** The
gateway contacts three OpenClaw-owned hosts without being asked. None of them
downloads or installs anything, and nothing in this deployment depends on any
of them. They are listed here because an operator sizing a firewall allowlist
would otherwise not expect them, and because two of the three are new in
`2026.8.1` — on the previous `2026.7.1` base the single call went to
`registry.npmjs.org`, which is no longer on the default path.

The world is enumerable rather than remembered. These three are the endpoint
constants the pinned image fetches from its own startup path, and inside that
image they live at `/app/dist/telemetry-DcLnYR14.js`,
`/app/dist/model-catalog-YrXw0PBH.js` and
`/app/dist/official-external-plugin-catalog-CBlJFCmU.js` — content-hashed
names, so they move with every upstream release. Re-derive the list against the
candidate image before any base bump; do not carry this table forward on
trust.

| Host and path | Trigger and cadence | Payload | Switched off by |
| --- | --- | --- | --- |
| `GET https://telemetry.openclaw.ai/api/latest-version` | Gateway start, then at most once per 24 h **after a check that succeeds** — the interval is measured from the last recorded ping, so a failed check records nothing and is re-attempted on a 60 s backoff instead; a host that denies this call sees repeated attempts, not one a day | No request body. A `User-Agent` header carrying `openclaw/<version> (<platform>; node/<node>; <arch>; <surface>)`. A JSON body of channel/provider/plugin counts is sent — as a POST — only when `telemetry.enabled` is `true`, which this release pins `false` | `update.checkOnStart: false` in `config/openclaw.json` |
| `GET https://catalog.openclaw.ai/models/v1/catalog.json` | Gateway start, then every 6 h | No request body; conditional-request headers only | `models.catalogRefresh.enabled: false` in `config/openclaw.json`. The update switches do not reach it: the refresh is scheduled before `update.checkOnStart` is consulted |
| `GET https://clawhub.ai/v1/feeds/plugins` | Once per gateway start, from the post-ready plugin data prewarm | No request body | **Nothing in configuration.** There is no key, no environment variable and no plugin-config path for it; `plugins.allow`, `plugins.enabled: false`, `update.checkOnStart: false`, `DO_NOT_TRACK` and `CI` all leave it running. Deny it in host egress policy, or accept it |

Three consequences:

- **Do not run `openclaw update`,** and do not act on an update banner or on
  the one-click update control the Control UI now offers beside it. The image
  is pinned by digest in `.env` and `deployment-lock.json`; upgrading in place
  would break the pinned-digest contract and every provenance gate that depends
  on it. Upgrades go through `scripts/update.sh` with a reviewed release, per
  §8.
- **Denying all three in an egress policy is a supported configuration.** Each
  failure is logged and degrades nothing; §5.1 names the exact lines to expect
  under a deny.
- **`DO_NOT_TRACK` is not the control here.** It only downgrades the version
  check from POST to GET. It does not stop that request and it does not reach
  the other two hosts. The two configuration keys above are the control, and
  the third host has none.

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
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env config --quiet
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
quarantine placeholder — the deployed stack writes quarantine copies into the
`vc-quarantine` named volume, not into this directory, and only when the
extract lane runs — see §9). A
*symlink* in either of those directories is still reported — the gateway would
follow it out of the intended tree. This is a
self-consistency check, not an external authenticity root: confirm separately
that the commit you hold is the one the project published, as described in
`README.md` under the developer quick start. A mismatch means
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
required. Retain the complete command transcript. To inspect the recorded lock,
read the file or re-validate it against the running deployment — neither writes
to it:

```sh
cat deployment-lock.json
python3 -B scripts/record_images.py --validate-live deployment-lock.json
```

The recorder itself is a writer, not a reporter. A no-argument
`python3 -B scripts/record_images.py` rewrites `deployment-lock.json` from the
current tree — re-stamping `baked_sources_sha256` from the host artifacts below
and `release_manifest_sha256` from `manifest.json`, without comparing either
against the lock it replaces — and prints just the lock's path, never its
contents. Run it standalone after
an edit to an image-baked artifact and it re-stamps the very digest the
`--validate-baked-sources` assertion below reads, so that assertion then reports
`PASS` against an image that was not rebuilt; the same run also clears the
`differing: release_manifest_sha256` abort that `backup.sh`'s internal
`--validate-live` step would otherwise raise (§9). Re-running the recorder alone
re-affirms the lock and leaves the running image stale.

The lock also records which image-baked artifacts the running image was built
from — the reviewed `workspaces/` tree, the trusted-context extension, the
exec-approvals seed, the dependency locks, and `Dockerfile.openclaw` itself: the
recipe is digested too, because editing it changes the image. Nothing
bind-mounts those, so an edit to a thesis, rubric, prompt or skill only reaches
the gateway through a rebuild. Assert at any time that a deployment reflects the
current tree:

```sh
python3 -B scripts/record_images.py --validate-baked-sources deployment-lock.json
```

A non-`PASS` result means `./scripts/bootstrap.sh` has not been re-run since the
edit; it is safe to re-run on a live deployment and re-records the lock. See
`CUSTOMIZATION.md`, "Policy edits reach the deployment only through a rebuild".

Do not proceed if the image build, package-version assertion, database password
proof, negative invalid-password proof, role restriction check, migration,
consumer `vcops db-check`, or `/readyz` fails.

The derived image installs the `runtime-packages/package-lock.json` graph with
`npm ci`, installs Python requirements with hash verification, and bakes the
reviewed `/workspaces` tree read-only. Before the gateway starts, the one-shot
`openclaw-state-init` service copies and validates the rendered config as
described above. It also loads the reviewed exec-approval seed — which stays at
the image-baked, read-only `/opt/openclaw-seed/exec-approvals.json`, outside
the state directory — into the `exec_approvals_config` row of the state
database, verifies the two exact data-steward executable paths by reading that
row back, removes any legacy `exec-approvals.json` — and the
`exec-approvals.json.doctor-importing` claim file beside it — from the state
directory, and asserts after seeding that neither has come back. It refuses to
run at all if either path is a symlink, so the removal cannot be aimed at
something else. The initializer runs as root with all
capabilities dropped except `CHOWN`, `DAC_OVERRIDE`, and `FOWNER`; it has no
network and exits before the gateway starts. Gateway and CLI remain non-root,
drop all capabilities, and gain no added capability.

Two things changed with the `2026.8.1` base and neither is cosmetic. The store
is the state database, not a JSON file: `loadExecApprovals()` reads
`exec_approvals_config`, and a leftover `$OPENCLAW_STATE_DIR/exec-approvals.json`
makes **every** approvals read and write throw rather than fall back — which is
why the initializer asserts its absence instead of tolerating it. And the
harness's own socket token now lives inside that row, so the old rationale for
leaving a writable JSON copy in the state volume no longer applies: there is no
file for the harness to maintain, and a check that compares against one is
checking something the runtime does not read.

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
| 5.1 Lobster, channel, search, Ollama and trusted-context extension versions; the ten pinned Debian package names, `python3` and `python3-venv` among them (their `3.11.2` is the python3-defaults revision, not the interpreter's — see the pin-scope comment in `scripts/run_g6_image.py` and §11); per-profile config validation; skill-workshop hook | `verify_offline.py --with-g6-image <image>` | The OpenClaw harness version: the probe reads the extensions and Debian packages listed here, never `openclaw --version`, so §5.1's first bullet stays yours (`check_env.py` refuses an `.env` whose `OPENCLAW_IMAGE` is not the pinned `2026.8.1@sha256:…` base, which is what constrains it between builds). Also record *your* live image IDs: `python3 -B scripts/record_images.py --validate-live deployment-lock.json` |
| 5.1 agent authority boundary (no direct Lobster, exec, config, cron, gateway or DB authority) | `validate_skill_system.py` and the `tests/infrastructure` exec-allowlist contract, both inside `verify_offline.py` | — |
| 5.1 rendered-config mode, ownership, digest and read-only mounting | `tests/infrastructure` plus the in-container initializer assertions exercised by `run_g8_deployment.py` | — |
| 5.1 `/healthz` and `/readyz` behaviour; private-path reachability | — | Yours: depends on your host and proxy |
| 5.2 migration names, checksums, and no-op replay | `verify_offline.py --with-g4-database` (applies and registers every migration twice) | Inspect `schema_migrations` once on your database |
| 5.2 `openclaw_runtime` cannot create schema objects or temporary objects, and holds only the reviewed table/function grants | `tests/g4/test_database_contract.py` asserts, against a live database, that the role cannot create schema or temporary objects, that DDL as the runtime role fails, and a spot-check of eight table privileges across six tables and eight function grants. The *whole* 42-table grant matrix is enumerated offline instead, by `tests/v3/test_runtime_grant_enumeration.py` against `docs/SCHEMA.sql`: every table carries exactly one reviewed grant, none grants `DELETE`/`TRUNCATE`, the append-only tables grant no `UPDATE`, the read-only trio stays read-only, and every `GRANT` line in that file names `openclaw_runtime` as its grantee | — |
| 5.2 `openclaw_runtime` is `NOINHERIT`, non-superuser, non-replication, non-`BYPASSRLS`, cannot create databases or roles, connection-limited, and holds no role membership in either direction | `scripts/rotate_runtime_role.sh` asserts exactly that predicate against `pg_roles`/`pg_auth_members` and fails closed; `bootstrap.sh` and `update.sh` both run it, so `run_g8_deployment.py` exercises it. **No offline gate covers it** — G4 builds its own throwaway role rather than applying `migrations/000_roles.sh` | Read the reconciler's output on *your* deployment (it runs on every bootstrap/update/rotate) |
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

The profile carries a twenty-first boolean, `channels.live_acceptance_completed`,
which is deliberately **not** one of those twenty and is **not** gated by
`check_customization.py`. It records that §5.5's channel matrix has passed, and
that matrix can only be exercised with the channel already selected and running
— so gating it would make channel activation unreachable. Keep it as your own
commissioning record: leave it `false` while the matrix is outstanding, set it
`true` when every row passes, and treat §5.6 and the retained evidence, not this
validator, as the enforcement point. Setting it `true` changes nothing the
software does.

Do not skip the restore drill in §5.4 — §5.0 records it as **never executed by
any gate**. Read the rest of that table by its `What is still yours` column
rather than by `Already proven by`: the restore drill sits in a row that *does*
name a gate, and so do the rows that still leave you the OpenClaw harness
version and your live image IDs, one look at `schema_migrations`, the role
reconciler's output on your deployment, the remaining twelve workflows, and the
channel matrix. A row a gate closes outright carries a `—` in that column.

### 5.1 Image and configuration

- Prove the runtime OpenClaw version is exactly `2026.8.1` and record the image
  digest/ID.
- Prove Lobster resolves from `/opt/openclaw-runtime` at exact `2026.6.11`; that
  Slack, Teams, and Discord — installed from the locked npm graph and then moved
  into `/app/dist/extensions/<id>` by `Dockerfile.openclaw` (see §10, "Channel
  plugins must stay under the harness's own extension scan root") — resolve
  there at exact `2026.8.1`; and that bundled Telegram at
  `/app/extensions/telegram` is exact `2026.8.1`. DuckDuckGo is **no longer**
  under `/app/dist/extensions`: `2026.8.1` stopped bundling it, so prove
  `@openclaw/duckduckgo-plugin` at exact `2026.8.1` under
  `/opt/openclaw-runtime/node_modules` instead, the way Firecrawl and Tavily are
  already proved.
- Run the pinned OpenClaw configuration validation, `doctor`, secret audit, and
  deep security audit inside the exact image. Each runs through the gateway
  container, in the same form as §5.2 and §5.3:

  ```sh
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw config validate
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw doctor
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw secrets audit
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw security audit --deep
  ```

  A correctly configured shipped deployment still reports some findings, and
  §5.6's "a warning is not a pass" rule does not mean commissioning is blocked
  by them — it means each one must be dispositioned. The expected set below was
  recorded against a real deployment of this release; if you see a finding that
  is **not** on this list, treat it as a genuine deviation and investigate it.

  From `openclaw config validate`:

  - Three `agents.entries` warnings on every profile, with `Config valid` and
    exit `0`:

    ```text
    ! agents.entries: Moved agents.list to keyed agents.entries.
    ! agents.entries: Materialized legacy per-surface agent ownership.
    ! agents.entries: Removed retired agents.entries.*.default markers.
    ```

    Expected. `2026.8.1` keys the agent roster under `agents.entries`; this
    release still declares it as the `agents.list` array, and the loader
    normalises the three differences in memory as it reads the config. The same
    three lines appear on `doctor`'s `stderr` prefixed `[config] warnings:` and
    in its `Doctor changes preview`, and the agents themselves resolve —
    `doctor` reports them under `agents.entries.<id>`. The validator classes
    them as warnings rather than errors and still answers `Config valid`. The
    remedy they imply is `openclaw doctor --fix`, which this section forbids:
    the runtime config is mounted read-only. Moving the key in
    `config/openclaw.json` is a reviewed configuration change carrying a re-pin
    — it is one of the twenty reviewed artifacts — and is not a commissioning
    action. Record the three lines with this disposition.

  From `openclaw security audit --deep`:

  - `tools.exec.fs_tools_disabled_but_exec_enabled` — the `data-steward` exec
    permission: the reviewed design, see "Sandboxing and security design" in
    `README.md`. `data-steward` holds exec for exactly two allowlisted launcher
    paths (`config/exec-approvals.json`) and read-only filesystem access —
    `read` is granted while `write`, `edit` and `apply_patch` are denied — which
    is the combination (those three mutating tools off, exec on) this check
    flags generically.
  - `gateway.probe_failed` (`missing scope: operator.read`) — expected. The
    audit's own probe authenticates with no operator scope against a
    token-authenticated gateway. It is the access control working, not a fault.
  - `models.small_params` (**CRITICAL**) — appears **only when the configured
    model is a small one**, which in practice means every Ollama deployment and
    any custom provider serving a small model. It does not appear on a hosted
    frontier model, which is why an OpenAI-mode commissioning of this release
    records `0 critical` while an Ollama-mode one records `1 critical` against
    the same warn/info baseline (the two baselines are tabulated after the next
    two entries, because the selected channel changes the warning count). The audit
    classifies any model at or below
    300B parameters as small and reports CRITICAL when one is granted
    `web_search`/`web_fetch`. Measured on an `ollama/llama3.2:1b` deployment it
    names the five specialists that hold web tools: `lead-signal-detector`,
    `outbound-scout`, `founder-researcher`, `traction-analyst`, and
    `market-mapper`.

    **This is not a false positive, and it cannot be configured away from
    `.env`.** `VC_WEB_SEARCH_PROVIDER` has no "off" value, so a shipped
    deployment always grants those five agents web tools. A small local model
    reading public web text is precisely the exposure `trust_boundaries.md` and
    the untrusted-content contract govern — the package's controls make public
    text data rather than instruction, but they do not make a 1B model good at
    honouring that boundary. This is why "whether the model honours the
    untrusted-content fencing it is given" stays on the BLOCKED list in
    `docs/PRODUCTION_READINESS.md` rather than being closed by any package gate.

    Disposition, and it is a decision you must record rather than a line to
    tick: either (a) run a model whose judgement you have benchmarked — the
    chosen-model quality/cost/context/tool-use qualification that
    `docs/PRODUCTION_READINESS.md` lists as a commissioning duty — and accept
    the finding with that evidence attached, or (b) remove
    `web_search`/`web_fetch` from those agents in `config/openclaw.json` and
    re-pin — it is one of the twenty reviewed artifacts, so this is the normal
    `init_customization.py --update-hashes` path — which clears the finding and
    costs the outbound-research lanes their search. Do not simply note it as
    expected and move on: on a small model this finding is describing a real
    property of the deployment you are commissioning.

  - `security.trust_model.multi_user_heuristic` — **on a `slack`, `discord`, or
    `telegram` profile only.** "Potential multi-user setup detected
    (personal-assistant model warning)", citing
    `channels.<provider>.groupPolicy="allowlist" with configured group targets`
    together with the un-sandboxed `exec` contexts. Expected, and it is
    restating this package's documented threat model back to you rather than
    reporting a misconfiguration: an allowlisted group destination *is* the
    reviewed multi-user design (README, "Channels, users, and document
    uploads"), and README's "Threat model" already states that this is a
    single-organization trusted-control-plane design and **not** isolation for
    mutually hostile tenants. **Its suggested fix must not be applied**:
    `agents.defaults.sandbox.mode="all"` is exactly the setting README's "Why
    OpenClaw sandbox mode is off" explains this package cannot use, because the
    fixed Lobster surface is unavailable in a sandboxed tool context. Record the
    finding with that disposition, and treat it as the prompt to re-confirm that
    every ID in `*_ALLOWED_USER_IDS` belongs to one organization that shares one
    trust boundary — if they do not, the correct answer is separate deployments,
    not a configuration change. The `msteams` profile does not raise it: its
    group scope is expressed under `channels.msteams.teams`, which the upstream
    heuristic does not scan.

  - `summary.attack_surface` (**INFO**) — the audit's own closing summary, not a
    fault. It is emitted on every profile and is the `1 info` in every baseline
    below, so it is listed here to keep the expected set complete: it reads
    `groups: open=0, allowlist=<0 on none, 1 on a channel profile>`, then
    `tools.elevated`, `hooks.webhooks`, `hooks.internal` and `browser control`
    all `disabled`, and restates the personal-assistant trust model. Nothing to
    apply or disposition beyond confirming those five values.

  Those per-profile differences change the totals, so compare against the right
  baseline — **and against the right form of the command.** `gateway.probe_failed`
  is a `--deep`-only check, so plain `openclaw security audit` reports exactly one
  warning fewer than the `--deep` form this section prescribes. Measured on this
  release with an OpenAI-mode configuration, on a live deployment and again by
  rendering each profile and running the audit inside the exact built image:

  | Command | `none`, `msteams` | `slack`, `discord`, `telegram` |
  | --- | --- | --- |
  | `openclaw security audit --deep` (this section) | 0 critical · 2 warn · 1 info | 0 critical · 3 warn · 1 info |
  | `openclaw security audit` (`docs/CHANNELS.md` step 7) | 0 critical · 1 warn · 1 info | 0 critical · 2 warn · 1 info |

  In each row the extra warning on the three channel profiles is the
  multi-user heuristic immediately above. An Ollama-mode or other small-model
  deployment adds `models.small_params` as a CRITICAL to whichever cell applies.

  You should **not** see `gateway.auth_no_rate_limit`. `gateway.bind` is `lan`
  because Docker forwards a published port to the container's network
  interface, so a loopback bind inside the container would make the gateway
  unreachable; host exposure is constrained by the Compose loopback publish
  (`127.0.0.1:…`). Brute-force mitigation is configured separately as
  `gateway.auth.rateLimit` (10 attempts / 60 s, 300 s lockout, no loopback
  exemption). If this finding appears, that block has been removed from
  `config/openclaw.json` or the rendered runtime config is stale.

  **This row is evidence that the limiter is configured, not that it works.**
  No gate in this package exercises it. G8's `negative-auth-proof` is a
  PostgreSQL credential probe — an invalid `PGPASSFILE` against the `postgres`
  service — and never reaches the gateway at all
  (`scripts/run_g8_deployment.py`, `negative_auth_proof`). Do not cite a green
  G8 as proof of gateway brute-force behaviour; if the deployment needs that
  proof, it is a commissioning test to write, not a row to copy.

  Separate from `gateway.auth.rateLimit`, and independent of it, the
  `2026.8.1` harness applies its own **non-configurable** write budget to the
  control plane: 30 calls per 60 s per (method, caller) pair for any method the
  method registry classes as a control-plane write. Exceeding it returns
  `UNAVAILABLE … rate limit exceeded for <method>; retry after Ns` and logs
  `control-plane write rate-limited method=… retryAfterMs=…`. There is no key
  to raise, lower, or disable it. It is well above anything the documented
  operator lanes generate, but a script that loops a control-plane write will
  hit it; treat the error as backpressure and retry after the interval it
  names, not as a fault.

  From `openclaw secrets audit`:

  - `gateway.auth.token` reported as plaintext: expected, and not a literal
    secret. Measured on this release, every profile reports exactly

    ```text
    Secrets audit: findings. plaintext=1, unresolved=0, shadowed=0, legacy=0.
    - [PLAINTEXT_FOUND] …:gateway.auth.token gateway.auth.token is stored as plaintext.
    ```

    The renderer writes the *environment substitution string*
    `"${OPENCLAW_GATEWAY_TOKEN}"` at that key, which the gateway expands when it
    loads the config; the audit reports the unexpanded string rather than a
    leaked credential. Note the contrast in the same output: the channel
    credentials are written as object-shaped SecretRefs
    (`{"id": "SLACK_BOT_TOKEN", "provider": "default", "source": "env"}`) and
    resolve cleanly, which is why `unresolved` stays `0` on a channel profile
    with its credentials present. Confirm the row rather than assuming it:
    `grep -c '"token": "\${OPENCLAW_GATEWAY_TOKEN}"'` on the rendered
    `config/runtime/openclaw.json` must return 1, and the file must contain no
    64-hex literal. If either check disagrees, a real token has been written
    into the config and the finding is not this one.

  From `openclaw doctor`:

  - A `Legacy config keys detected` block naming exactly one key:

    ```text
    - agents.list: agents.list moved to keyed agents.entries. Run "openclaw doctor --fix".
    ```

    Expected on every profile, and it does **not** clear: `openclaw doctor
    --fix` is the one command this section forbids, and the shipped
    `agents.list` is dispositioned under `openclaw config validate` above. It
    arrives beside a `Doctor changes preview` listing those three
    normalisations among its five preview lines, and a closing `Doctor` block whose
    lines each begin `Run "openclaw doctor --fix"`. Nothing is degraded: the
    loader applies the normalisation on every start, and only persisting it is
    refused.
  - twenty-four `Model "${VC_PRIMARY_MODEL}" specified without provider.
    Falling back to "openai/${VC_PRIMARY_MODEL}"` lines — six naming
    `${VC_PRIMARY_MODEL}` and eighteen naming `${VC_FAST_MODEL}`, since most
    agents are configured on the fast tier and doctor walks the agent list more
    than once — and `openclaw models status`
    showing the harness default `openai/gpt-5.5` — a diagnostic artifact, not a
    misconfiguration. `doctor` reads the config text without the environment
    substitution the runtime performs, so it sees the literal `${VC_PRIMARY_MODEL}`.
    Confirm the real behaviour instead of the diagnostic: a live agent run
    resolves the configured model (`requested=openai/<your VC_PRIMARY_MODEL>`),
    which is the evidence for this row. `plugins.allow` and memory-provider
    migration hints are legacy-key advice that does **not** apply to this
    configuration and must not be applied.
  - **On a channel profile only** (`PRIMARY_CHANNEL` other than `none`), one
    additional `Doctor warnings` block: `Agent "vc-chief" is routed from
    channel "<provider>", but the message tool is unavailable for that agent;
    explicit channel actions such as sendAttachment, upload-file, thread-reply,
    or reply can fail. Add "message" to the agent tool allowlist, add
    "group:messaging", or switch the agent to a profile that includes messaging
    tools.` Expected, and **none of the three suggested edits may be applied.**
    Withholding channel-action tools from every agent is the reviewed design
    (`workspaces/vc-chief/vc/channel_policy.md`, and the "Tools" row of
    README.md's sandboxing table): the chief answers in the reply stream the
    channel already owns and never performs an explicit channel action. The
    warning describes a capability this deployment deliberately does not have,
    not a misconfiguration. Record it with that disposition.
  - A `Command owner` block — `No command owner is configured.` — on **every**
    profile including `none`, whose `Fix:` line suggests
    `openclaw config set commands.ownerAllowFrom '["telegram:123456789"]'`.
    Expected, and **that edit must not be applied.** A command owner gates
    owner-only *chat* commands (`/diagnostics`, `/export-trajectory`, `/config`,
    chat exec approvals); this deployment exposes no chat command surface at
    all. Verified on all five rendered profiles, the effective `commands` block
    is `native`, `nativeSkills`, `text`, `bash`, `config`, `mcp`, `plugins`,
    `debug` and `restart` — every one of them `false` — so there is no
    owner-scoped command for an owner ID to protect. `commands.useAccessGroups`
    no longer appears in that block: `2026.8.1` retired the key and made
    access-group scoping unconditional, so the posture it selected is now the
    only behaviour rather than a setting. Expect one fewer entry than the
    `2026.7.1` commissioning record shows, and do not read its absence as the
    scoping having been turned off. Operator actions run
    through the administrative control plane
    (`vcops-operator`, `vcrun-control`) under `VCOPS_OPERATOR_ID`, never through
    a channel. Setting `commands.ownerAllowFrom` would also grant a channel
    identity a privileged role the threat model deliberately withholds from
    channel identities, and `config/openclaw.json` is a hash-pinned reviewed
    artifact, so the edit costs a re-pin for a control this deployment does not
    use.
  - A `Security` block whose first entries read `… is broader than the host exec
    policy` — **twelve of them**: one global `tools.exec`, then one per agent for
    the eleven agents other than `data-steward` (which appears in the same block
    under the separate filesystem/exec entry instead). Each ends `Effective host
    exec stays security="deny" ask="off" because the stricter side wins`. Expected,
    and its `Fix` ("align both files or enable Web UI, terminal UI, or chat exec
    approvals") **must not be applied.** The two files are meant to disagree in
    exactly this direction: `config/openclaw.json` declares
    `tools.exec.mode="allowlist"`, while the image-baked
    `config/exec-approvals.json` seeds `defaults.security="deny"` with the two
    reviewed `data-steward` launcher paths as its only entries. The harness
    resolves the pair by taking the stricter side, which is the reviewed
    boundary. Enabling any interactive approval surface would create the chat
    exec-approval path the threat model withholds. The same block then carries
    the `data-steward` filesystem/exec entry and the `Gateway bound to "lan"`
    warning, both dispositioned above.
  - A `Startup optimization` block suggesting `NODE_COMPILE_CACHE` and
    `OPENCLAW_NO_RESPAWN`. Expected on every profile; it is host-tuning advice
    for low-power machines, not a finding about this configuration. Neither
    variable is part of the reviewed environment contract, and `check_env.py`
    rejects both in `.env` as unknown keys.
  - A `Plugin registry` block — `Persisted plugin registry is missing or stale.`
    Expected on every profile, and it does **not** clear: its only remedy is
    `openclaw doctor --fix`, which this section forbids because the runtime
    config is mounted read-only. The gateway builds its effective plugin set
    from that config on every start — `openclaw doctor`'s own `Plugins` block
    reports `Errors: 0` and the gateway log lists the loaded plugins by name —
    so the persisted cache in `state/openclaw.sqlite` is an optimization this
    deployment does without.
  - A `State integrity` block. On every profile it reports `OAuth dir not
    present (~/.openclaw/credentials). Skipping create because no
    WhatsApp/pairing channel config is active` — expected, no pairing channel is
    configured. On a deployment where **no agent has run yet** it additionally
    reports `CRITICAL: Session store dir missing
    (~/.openclaw/agents/<agent>/sessions)`. That one is a first-run artifact, not
    a fault: the store is created by the first agent session. Measured on this
    release — one `openclaw agent --agent vc-chief` run creates
    `sessions/sessions.json` and the CRITICAL is gone from the next `doctor`.
    Run one agent turn before recording this row, and treat the CRITICAL as
    resolved only once you have seen it clear.
  - Informational `Skills status`, `Plugins`, and `Memory search` blocks. Not
    findings: they report counts (eligible/missing/incompatible skills, loaded
    and disabled plugins with `Errors: 0`) and confirm `Memory search is
    explicitly disabled (enabled: false)`, which is the reviewed design — see
    "Memory and personalization" in `README.md`. The counts vary with host
    platform, so record yours rather than matching a number from here.

  In the gateway log at every start:

  - `failed to promote config last-known-good backup: Error: EROFS: read-only
    file system, open '/home/node/.openclaw-config/openclaw.json.last-good'` —
    expected, and logged at warn level by the harness (`log.warn`, subsystem
    `gateway`), so read the gateway log at warn, not error. The level is not
    adjustable here: `OPENCLAW_LOG_LEVEL` is not part of the reviewed
    environment contract, `check_env.py` rejects it in `.env` as an unknown
    key, and the Compose gateway service does not forward it. Two reload-path
    wordings exist and have different status. `config reload last-known-good
    promotion failed: …` appears whenever an `openclaw-state-init` run
    delivers a new config while the gateway is still up — which is exactly
    what §6's channel-activation sequence does — so treat it as expected
    there and as a deviation anywhere else. `config reload in-process
    last-known-good promotion failed: …` should never appear: `commands.config`
    is pinned `false` and the config is mounted read-only, so the gateway
    never rewrites its own config. The runtime config is
    mounted read-only by design (§5.1 below proves that mount), so the harness
    cannot write its last-known-good copy beside it. Nothing is degraded: the
    config the gateway loaded is the one the initializer validated.
  - `remote model catalog refresh failed` — logged at **info** level, not warn.
    With `models.catalogRefresh.enabled` pinned `false` it should not appear at
    all: a disabled refresh returns without making a request and logs nothing.
    Seeing it therefore tells you the pin is missing from the rendered runtime
    config — a disabled refresh returns before it makes a request — and that
    the request it did make failed. A host denying `catalog.openclaw.ai` is the
    usual cause, but the same line covers any DNS, TLS, timeout, non-200 or
    malformed-bundle failure, so treat the missing pin as the finding and the
    cause of the failure as still to be established. Re-render and re-bootstrap.
    Nothing is degraded either way; the gateway uses the catalogue bundled in
    the image.
  - `post-ready gateway data prewarm failed for plugins: …` — expected on any
    host whose egress policy denies `clawhub.ai`. This is the one call in §2's
    table that no configuration key disables, so on a deny-all host it appears
    at every start. The fetch is fire-and-forget and its only consumer is the
    Control UI's plugin catalogue, which this deployment does not use.
  - `update available (latest): … Run: openclaw update` — **should not appear.**
    `update.checkOnStart` is pinned `false`, so the check never runs. If you see
    it, the pin is missing from the rendered runtime config: re-render and
    re-bootstrap rather than ignoring the line. See §2's egress table.

  **Never run `openclaw doctor --fix` here.** The runtime config is mounted
  read-only by design, so it fails with `EROFS`, and its suggested edits are
  the ones listed above as not applicable. Record the findings and their
  disposition as the evidence for this row.
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
  and a non-chief caller are blocked by the image-owned hook. `2026.8.1` widens
  the tool's own action set from eight to fifteen, so record the whole world
  rather than the five that pass: the guard admits `create`, `update`,
  `revise`, `list`, `inspect`; it refuses `apply`, `reject`, `quarantine` as
  reviewed policy; and its fail-closed default now also refuses
  `restore_collection` and `complete` (lifecycle, same rationale) and `read`,
  `prepare_patch`, `patch`, `evaluate`, `history` (authoring and inspection).
  Those last five are a **deliberate loss for this release**, not a defect:
  extending the allowlist to reach them is a behaviour change that needs its
  own review, and until it happens the chief cannot patch a live skill in place
  or run proposal evaluators. Expect the refusal, and record it.

### 5.2 Database and helper

- Run `db-check` from both consumer images. There is no `vcops` on `PATH`;
  use the absolute wrapper, and override the CLI service's own entrypoint:

  ```sh
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    exec openclaw-gateway /workspaces/vc-chief/vc/bin/agent/vcops db-check
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
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
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw tasks audit
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
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
  `models.*` and `search.*` byte-identical to that `.env`. Then, before
  re-pinning, run
  `python3 -B scripts/check_customization.py config/customization-profile.json .env`
  and read the `reviewed artifact changed after review: <path>` lines it prints.
  Account for each path it names — a deliberate edit of yours, or a change this
  release made to a shipped artifact. A path you cannot account for is a
  customization that was not carried across; re-pinning it is how you lose it,
  silently, because the re-pin reports only a count and no later gate can see
  the reversion (§9, "Never regenerate hashes around a change you cannot account
  for"). Only then re-pin with
  `python3 -B scripts/init_customization.py --update-hashes`, and confirm
  `python3 -B scripts/check_customization.py config/customization-profile.json .env`
  passes. A production profile that selects a channel will not validate here. That `.env` **must carry the same `BACKUP_HMAC_KEY` that was in force
  when the backup was written** — `restore.sh` authenticates the checksum
  manifest with it and aborts with "backup authenticity verification failed"
  otherwise. A fresh key on the recovery host makes every existing recovery
  point unrestorable, so treat the key as part of the recovery point and store
  it independently of the archives. The same `.env` must also carry an
  `OPENCLAW_STATE_ARCHIVE_MAX_BYTES` at least as large as the value in force
  when the backup was written (empty means the 2 GiB default): the backup
  records its effective bound in `BACKUP_MANIFEST` and `restore.sh` fails
  closed pre-mutation, naming the variable and the required minimum, if the
  target's bound is smaller. Size the target's `${TMPDIR:-/tmp}` for private
  restore staging per the budget in `OPERATIONS.md`, "Rollback and restore",
  which is the single source of truth for that arithmetic: the extracted trees
  must survive validation, restore re-reads the state and quarantine tiers back
  from the deployment after mutation begins, and the compressed copies it writes
  there are never removed — so an `ENOSPC` strikes after the production database
  has already been replaced. Then run `./scripts/bootstrap.sh` so the
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
then re-enable only the reviewed profile. That is matrix row CH-12 in
`docs/CHANNELS.md`, and no shipped gate exercises it: `run_g8_deployment.py`
builds its throwaway `.env` from `.env.example` and therefore runs at
`PRIMARY_CHANNEL=none` from bootstrap to teardown. The rollback proof is yours
to produce and retain, like the rest of the channel matrix (§5.0).

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
`approvals.allowed_channel_ids` must be the one-element list holding the
selected profile's *conversation* ID from `.env` (`docs/CHANNELS.md`,
"Destination IDs and the reviewed profile", names the variable per channel; a
Teams team ID or a Discord guild ID does not belong there), and the change
record must note the review — otherwise the next lifecycle validation fails
closed on the profile/environment mismatch.
Then rerun:

```sh
./scripts/check_env.sh .env
python3 -B scripts/check_customization.py config/customization-profile.json .env
python3 -B scripts/render_channel_config.py .env
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env config --quiet
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env run --rm --no-deps openclaw-state-init
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env up -d --wait --force-recreate --no-deps openclaw-gateway
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env --profile tools up --force-recreate --no-deps --no-start openclaw-cli
```

The `openclaw-state-init` run is required, not optional: the gateway reads the
rendered config from the runtime-config volume, and that one-shot service is the
only writer of it. Recreating the gateway alone leaves the previous channel
config mounted. Re-running `./scripts/bootstrap.sh` does the same thing.

The last line is required for the same reason `docs/OPERATIONS.md` gives when
rotating a secret: `openclaw-cli` sits behind the `tools` profile, so the
gateway's `--force-recreate` does not touch it, and the stopped container keeps
the provider and channel values — and the `OPENCLAW_GATEWAY_TOKEN` — it was
created with, visible to anyone who can run `docker inspect`. Recreating it
against the new `.env` is what makes the change complete rather than
partial. (This is distinct from §9's restart-after-failure case, where nothing
in the configuration changed and `openclaw-cli` genuinely needs nothing.)

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
reviewed artifacts against the new tree — before it takes the lifecycle lock.

`inbox/` is bind-mounted from the package directory (`docker-compose.yml`,
`./inbox:/inbox:ro`), not held in a named volume, so a new package directory
starts with the shipped placeholder alone. Copy the deployed revision's
`inbox/` contents across too if you want the operator lane to keep seeing them;
the pre-update recovery point captures whatever the new directory's `inbox/`
holds when `update.sh` runs. Operator payload under `inbox/` is excluded from
`manifest.json` and tolerated by `verify_release.py --pristine`, so carrying it
across does not affect the re-pin below.

Copy the contents as plain files. `update.sh` and `backup.sh` both refuse, before
touching anything, an inbox entry a recovery archive cannot represent. Five of
the six classes are about the entry's NAME or KIND: a control character or a
backslash in the path, a symlink, anything that is not a regular file or
directory, and a **hard link** — which `cp -al` and `rsync --link-dest` produce
and `cp -a` preserves from the source. The sixth is different in kind: a directory
the scripts cannot descend, which makes the enumeration itself fail. That one is
not a malformed name — it means the checks above were not applied to every
entry, so the run cannot certify the inbox — and its message hands you the
`find` command to run yourself. Correct the permissions of what it reports; do
not remove it. An unreadable regular *file* is a different case and is not
caught here: `tar` reports it and the backup fails during the archive instead.

The refusal ends `nothing has been stopped`, so the deployment is untouched
and you can correct it and re-run. Most name the entry. A control character in a
name and a failed enumeration do not: such a name cannot be printed usefully and
would corrupt the terminal, and a failed enumeration never learned which entry
stopped it, so those refusals give you the `find` command to run instead of
quoting anything. To detach a hard-linked entry
without changing its bytes:

```sh
cp inbox/<entry> inbox/<entry>.detached && mv inbox/<entry>.detached inbox/<entry>
```

`validate_recovery_archive.py` rejects all five NAME-and-kind classes when it
verifies the recovery point, so the guard refuses early rather than after the
quiesce. It cannot see the sixth: a directory that cannot be
descended produces no malformed member name at all, so the validator has nothing
to reject. The guard stops before the quiesce instead, because a run whose
enumeration failed cannot certify the inbox.

So re-pin afterwards. First run
`python3 -B scripts/check_customization.py config/customization-profile.json .env`
and read the `reviewed artifact changed after review: <path>` lines it prints.
Account for each path it names — a deliberate edit of yours, or a change this
release made to a shipped artifact. A path you cannot account for is a
customization that was not carried across; re-pinning it is how you lose it,
silently, because the re-pin reports only a count and no later gate can see the
reversion (§9, "Never regenerate hashes around a change you cannot account
for"). Only then:

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
credential, role, migration, consumer, and readiness reconciliation. It records
new image IDs only after those checks pass. If any later step fails, consumers
remain stopped; restore the verified pre-update recovery point or repair the
reviewed release. If the failure landed after the migrations applied, the
schema is already ahead of the recorded lock: a retry's pre-update backup
refuses rather than stamp the old version onto the new schema, so the valid
rollback target is the **first** attempt's recovery point, restored with the
package revision that matches it. Repeat all G8 checks affected by binary, schema,
configuration, provider, workflow, or model changes that affect the deployed
environment.

On the `2026.8.1` base the point of no return arrives earlier than the first
gateway start. The one-shot `openclaw-state-init` service is a
`service_completed_successfully` precondition of the gateway, and its approvals
write and read-back move `state/openclaw.sqlite` from `PRAGMA user_version` 1 to
15 — measured; a read-only `openclaw approvals get` under `2026.8.1` does it on
its own. A `2026.7.1` gateway then refuses that volume and exits 1 (`uses newer
schema version 15; this OpenClaw build supports 1`), so reverting the image and
the package alone is not a rollback: the advanced state volume stays. Restore
the pre-update recovery point instead, and do not read a `2026.7.1` CLI's exit
0 as proof that it worked — the CLI logs the same refusal as a migration
warning, exits 0, and reports an empty exec allowlist at `security: "full"`,
which is fail-open. Verify the pre-update recovery point is restorable before
the update runs, not after.

Rollback uses the prior package revision, its exact image digest, and a
compatible database/state backup together. Do not point an older binary at a
newer schema unless upstream explicitly documents compatibility. For channel
rollback, run §6's sequence with `PRIMARY_CHANNEL=none`: clear all channel
fields, set the profile's `channels.selected` back to `none` and
`approvals.allowed_channel_ids` to `[]`, validate, render, **re-run
`openclaw-state-init`**, force-recreate the gateway, and prove disconnection.
The state-init run is not optional here either — recreating the gateway alone
leaves the previous channel config mounted, so the deployment would still be
connected while the rollback looked complete. `docs/CHANNELS.md` row CH-12 is
where that proof is recorded.

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
3. Update `config/openclaw.json` (both `skills.entries` and the `skills` list of
   every agent that should hold it), the owning agent's `AGENTS.md` and
   `TOOLS.md`, `workspaces/vc-chief/vc/RESOLVER.md` (the `discovers N shared
   skills` line **and** the canonical skill list below it), any canonical
   schemas/helpers/workflows, public documentation, and positive, negative,
   adversarial, and routing fixtures.

   Two of these bite in ways the wording above does not make obvious, and both
   were confirmed by walking this procedure end to end:

   - **The canonical schemas are mirrored, and the mirror is compared
     byte-for-byte.** `workspaces/schemas/lead-router.output.schema.json` carries
     the routable skill enum, and `workspaces/vc-chief/vc/schemas/` holds a copy
     the chief reads at runtime. Editing one and not the other fails
     `tests/contracts` on `test_mirror_is_complete_and_byte_identical`, not on
     anything that names the skill.
   - **The count is frozen in the test suite as well as in the validator.**
     `tests/v3/test_orchestration_and_customization.py` pins both the resolver
     string and the skill total; `tests/v3/test_skill_agent_production.py` pins
     the `(skills, agents, workflows)` triple; and `SkillCountPinTests` in
     `tests/v3/test_doc_tree_consistency.py` binds every tracked `.md` that
     states the count. The tracked documents that state it are `README.md`,
     `docs/PRODUCTION_READINESS.md`, `docs/V3_RELEASE_EVIDENCE.md`,
     `docs/RUNBOOK.md` (this section), `evals/V3_EVAL_RESULTS.md`,
     `research/agents/02-lead-router.md`,
     `workspaces/vc-chief/vc/RESOLVER.md`,
     `workspaces/vc-chief/vc/system_health.md`,
     `workspaces/vc-chief/vc/eval_fixtures.md`,
     `workspaces/vc-chief/vc/governance_lint.md`, and
     `workspaces/shared-skills/resolver-check/SKILL.md`.
4. Deliberately update the exact inventory in
   `scripts/validate_skill_system.py`; an unexplained count change is a release
   failure. Note the corollary of that rule: a *deliberate* change has to be
   made everywhere in step 3 at once, or the gates go red for reasons that look
   like the defect this rule exists to catch.
5. Run the official `skill-creator` `quick_validate.py` against the new skill.
   That tool is not part of this package; it is bundled inside the pinned
   OpenClaw image and runs with the image's own `python3`:

   ```sh
   docker run --rm -v "$PWD/workspaces/shared-skills:/skills:ro" \
     --entrypoint python3 vc-lead-research:3.0.1 \
     /app/skills/skill-creator/scripts/quick_validate.py /skills/<skill-name>
   ```

   Then run `python3 -B scripts/validate_skill_system.py`. It reports the new
   total and names any stale touchpoint **it can see** — and its reach is
   narrower than step 3's list, so do not treat a clean run as proof that step 3
   is finished. It reads `config/openclaw.json`, `config/exec-approvals.json`,
   `workspaces/shared-skills/*/SKILL.md`, each agent's `AGENTS.md`/`TOOLS.md`,
   `RESOLVER.md`, `workspaces/schemas/`, the `.lobster` inventory,
   `runtime-extensions/vc-trusted-context/index.js` and `vcrun.py`. It opens
   nothing under `docs/`, `evals/` or `tests/`.

   That leaves two classes of touchpoint to close by hand:

   - the two `tests/v3` files above, which freeze the counts — these do fail
     loudly, but under `verify_offline.py`, not under this validator; and
   - the documents that state the count in prose. `SkillCountPinTests` in
     `tests/v3/test_doc_tree_consistency.py` now fails the offline gate if any
     tracked `.md` outside `_internal/` states a skill count that disagrees with
     `validate_skill_system.py`'s inventory, so this is no longer an unchecked
     class — but the test tells you *that* a file drifted, not what the new
     prose should say. Enumerate them yourself before you move on, over the
     whole tree rather than a curated path list, because the list was short by
     four files until the fifteenth pass. With the shipped inventory the
     outgoing number is `26`:

     ```sh
     git grep -n '\b26\b' -- '*.md'
     ```

     From a non-git export, use:

     ```sh
     grep -rn --include='*.md' '\b26\b' . --exclude-dir=_internal --exclude-dir=.git
     ```

     `RESOLVER.md`'s inventory line is the one hit `validate_skill_system.py`
     itself covers; the rest are yours.

   **Regenerate the manifest before the full gate, not after.**
   `python3 -B scripts/build_release_manifest.py` first, then the complete
   locked virtual-environment gate. `verify_offline.py` includes the
   manifest-currency and pristine checks, so running it against a tree that has
   gained a `SKILL.md` and not been re-pinned fails on those two every time —
   which buries the failures worth reading underneath two that are expected.
6. Rebuild the image, run disposable Postgres, retrieval-scale when affected,
   and exact-image gates, then verify the release manifest again.
   Once the rebuilt image is running, confirm the harness itself accepts the
   new skill: `openclaw skills check --agent <owner-agent> --json` must list it
   as visible. This is what catches a skill that loads locally but pushes the
   agent past `skills.limits.maxSkillsPromptChars`, which no offline gate sees.
7. Obtain named code/security/privacy review and deploy through the normal
   update procedure. Confirm routing and rollback in commissioning.

Rejecting or quarantining a proposal is likewise an authenticated operator
lifecycle decision; an agent cannot make it. Preserve the reason and audit
record. Autonomous transcript review remains disabled.

## 9. Incident fail-closed actions

- **Credential exposure:** set the affected channel to `none`, stop consumers,
  rotate the credential, inspect audit/provider logs, and rerun its live matrix.
- **Role reconciliation failed** (`openclaw_runtime role restrictions did not
  reconcile`, or any `rotate_runtime_role.sh` failure): **this is a recoverable
  state and the remedy is to re-run the script, not to restore.** Read the four
  phases below to find out what the failed run had already done. Whether the
  consumers are still up separates phase 4 from the three before it — the
  script's own output names which command failed — so list them first:

  ```sh
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    --profile tools ps --all
  ```

  `--all` is the load-bearing flag: a bare `ps` omits stopped containers, which
  makes a consumer this script stopped indistinguishable from one that was never
  created — both render as an empty listing. `--profile tools` is carried for
  consistency with `scripts/update.sh`, `scripts/backup.sh` and
  `scripts/restore.sh`, which use one `compose` helper for both `ps` and the
  profile-gated `stop`; measured on this host's Compose, `ps --all` lists
  `openclaw-cli` with or without it, so do not read the profile flag as what
  makes the CLI visible. A `postgres` row in state `running` is also the
  "Postgres is up" confirmation the re-run below needs.

  The four phases below describe a **direct** `./scripts/rotate_runtime_role.sh`
  run. `scripts/bootstrap.sh` and `scripts/update.sh` both call it, and both arm
  their own mutation flag *before* the call — deliberately, because
  `trap ... HUP INT QUIT TERM` runs between commands, so a signal arriving during
  the rotation must be handled with the flag already set. A refusal *inside* the
  rotation during phases 1–3 therefore runs the **caller's** cleanup, which stops
  `openclaw-gateway` and the `openclaw-cli` container and prints that it has done
  so — even though the rotation itself changed nothing, and its own cleanup would
  have stopped nothing. Both callers pre-check
  `/tmp/vc-lead-research-v3-rotation.lock` before arming, so the one crash
  state `docs/OPERATIONS.md` documents as an expected leftover now refuses while
  production is still running; what remains in that window is losing the race for
  that lock, and the rotation's own private `.env` snapshot. **If the message you
  saw came from `bootstrap.sh` or `update.sh` and says the consumers are stopped,
  believe it over the phase text below**, and bring the gateway back after
  correcting the cause:

  ```sh
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    up -d --wait --force-recreate --no-deps openclaw-gateway
  ```

  `openclaw-cli` needs nothing: it is profile-gated and runs as a one-off under
  `docker compose run`, so "stopped" is its normal state between turns.

  1. **Lock acquisition, `check_env.sh`, or `check_customization.py`** — nothing
     has been touched. Correct what it reported and re-run.
  2. **`render_channel_config.py`** — nothing has been written either. The
     renderer writes `config/runtime/secrets/` as the last thing it does, after
     every validation has passed, so a render that fails a check reports `FAIL`
     having left that directory alone: the four files still hold the values of
     the last render that *succeeded*, which need not be what `.env` now says.
     (The one exception is a render that fails while writing — an `OSError` from
     the filesystem — which can leave the four mixed; that error names the path
     it failed on.) Correct and re-run.
  3. **`compose config --quiet`** — the render did succeed, because
     `scripts/rotate_runtime_role.sh` renders before it validates the Compose
     configuration, so the four files under `config/runtime/secrets/` now hold
     the `.env` values. In this phase and in phase 2 no database password has
     changed, and a **direct** rotation has stopped no consumer — read the caller
     note above if you reached this through `bootstrap.sh` or `update.sh`.
     Correct and re-run.
  4. **At or after the consumer stop the script prints** — the gateway and CLI
     are stopped, and the database passwords may now be mid-rotation.
     `migrations/000_roles.sh` sets `openclaw_runtime` to `NOLOGIN`, installs
     both passwords in two further `psql` invocations, and restores `LOGIN` only
     at the end; a failure anywhere in that window leaves the runtime role
     unable to log in, and which password is stored depends on how far the
     script reached — the runtime `\password` runs inside the window, so an
     earlier failure leaves the previous one in place. Either way the remedy
     below is the same.

  In every one of those phases the fix is the same, because **the reconciler does
  not need the database's current passwords.** Every credential-changing
  statement in `migrations/000_roles.sh` connects over the container's Unix
  socket, which the pinned image's generated `pg_hba.conf` trusts, so the script
  installs whatever `.env` holds regardless of what Postgres currently stores.
  Confirm Postgres is up, confirm `.env` holds the passwords you intend to
  deploy, and re-run `./scripts/rotate_runtime_role.sh`; it is idempotent.

  If you want to know which credential is live before re-running, probe each role
  from the Postgres container **over TCP**. `.env` holds two database passwords:
  `POSTGRES_PASSWORD` is the `openclaw_owner` password and `OPENCLAW_DB_PASSWORD`
  is the `openclaw_runtime` one.

  ```sh
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    exec postgres psql -h 127.0.0.1 -U openclaw_owner -d openclaw -W -tAc 'select 1'
  ```

  `-W` makes `psql` prompt. Do not pass the password with `-e PGPASSWORD=…`: that
  puts a live credential into the host `docker compose` argv, where any local user
  can read it with `ps`, and into your shell history — during a credential
  incident. `migrations/000_roles.sh` refuses to do this for the same reason
  ("Passwords live briefly in mode-0600 files and never enter argv or exports").
  Repeat the command with `-U openclaw_runtime` to probe the runtime role.

  The `-h 127.0.0.1` is load-bearing and this test is worthless without it. The
  generated `pg_hba.conf` begins `local all all trust`, so a connection over the
  container's Unix socket — which is what plain `psql -U openclaw_owner` uses —
  succeeds with **any** password, including a wrong one. Only the `host` rules
  carry `scram-sha-256` (`POSTGRES_HOST_AUTH_METHOD` and `--auth-host` in
  `docker-compose.yml` set them), so TCP is the only path that tests the
  credential. The probe has three outcomes, not two:

  | Output | Meaning |
  | --- | --- |
  | `1` | this credential is live |
  | `FATAL:  password authentication failed for user "<role>"` | `.env` and the database disagree for that role |
  | `FATAL:  role "openclaw_runtime" is not permitted to log in` | the run aborted inside the `NOLOGIN` window (phase 4). The password may be correct. Re-run the script. |

  Restoring from a recovery point (§5.4) is **not** part of *this* procedure —
  re-running the rotation is what reconciles the credentials, and a restore
  neither diagnoses nor repairs a credential mismatch. It is warranted only if
  the database itself is unrecoverable: a corrupt cluster or a lost volume, which
  the probes above do not diagnose.

  That is scoped to the rotation. It does **not** override `update.sh`'s own
  failure message, which says "Repair the release, or restore the verified
  pre-update backup if its final directory was published, before restarting
  traffic": an update that failed *after* publishing its pre-update recovery
  point has a different remedy, because there the recovery point is a known-good
  prior state of the whole deployment rather than an attempt to fix credentials.
  If the message you are holding came from `update.sh`, follow §8's rollback.
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
- **Malicious document:** do not open it with an office application, and
  preserve the rejection evidence. **Do not assume a quarantine copy exists —
  read `details.quarantine.materialized` in the failed step's returned
  `{code, message, details}` object.** That field is the authority, and it is
  `false` more often than the volume's name suggests:
  - The **preview** lane never quarantines. It is the read lane and performs no
    mutation. Both shipped intake workflows (`document-ingest`,
    `inbound-intake`) run `document-preview` first, and every inspection-stage
    class — magic/MIME mismatch, macro or legacy Office format, encryption,
    archive expansion or member limits, active content, page limits, oversize —
    is raised there. Lobster stops at the first failing step, so in a normal
    workflow rejection the document never reaches the extract lane at all.
  - The **extract** lane attempts a copy for the failures raised inside its
    error handler, which opens before `inspect_document` — so inspection-stage
    rejections route through the same quarantine lane as post-snapshot parse
    failures. This is reachable by an operator running
    `bin/vcops-operator document-extract` by hand, and in the workflow lane when
    the bytes change between the preview and extract steps.
  - **The attempt can still copy nothing.** `quarantine_document` returns
    `materialized: false` for an oversized document (it refuses to copy bytes
    above the same `MAX_DOCUMENT_BYTES` that raised `document_too_large`), for
    any input it cannot safely read — symlink, outside the intake root,
    non-regular, empty, missing — and, as `quarantine_write_failed`, when the
    copy or its metadata marker cannot be written, which a source file with a
    very long extension can cause because the quarantine name carries that
    extension. `quarantine_write_failed` reports that *this* rejection
    published nothing new, not that the volume is clean: quarantine names are
    content-addressed, so a copy and marker published by an earlier rejection
    of the same bytes are deliberately retained rather than removed by the
    failing one.
    Failures raised before the handler opens
    (workflow-claim and media-context validation) or after it closes
    (`artifact_integrity_conflict`, `artifact_classification_conflict`,
    `lineage_mismatch`, the replay `idempotency_payload_mismatch`) never reach
    it and carry no `quarantine` key at all.

  When `materialized` is `false` or absent, the artifact to preserve is the
  original itself — under the OpenClaw inbound-media root for a channel
  attachment, or `./inbox` for an operator drop — together with the returned
  `{code, message, details}` object. Record the hash and provenance from there.
  When it is `true`, `vc-quarantine` holds hostile bytes at the recorded path.

  A `false` result describes this rejection, not the volume's contents. After a
  `quarantine_write_failed` on bytes an earlier rejection already recorded, the
  copy and marker for exactly those bytes are still on `vc-quarantine` under
  their content-addressed names. Decide teardown handling from whether any
  rejection has recorded a copy, not from the latest result alone.
- **Integrity mismatch:** if the reported paths are edits you deliberately made
  — customized policy artifacts, a replaced rubric — re-pin **both** inventories
  and re-run the gate:

  ```sh
  python3 -B scripts/init_customization.py --update-hashes
  python3 -B scripts/build_release_manifest.py
  ```

  The manifest re-pin alone clears `verify_release.py --pristine` and stops
  there, which reads like the remediation is complete. It is not: most
  customizable policy artifacts — the rubric this entry names, `thesis.md`,
  `exclusion_criteria.md`, `config/openclaw.json`, the eval fixtures — are also
  among the twenty hash-pinned artifacts recorded in
  `config/customization-profile.json`, and `bootstrap.sh` runs
  `check_customization.py` as its second step. Skip the profile re-pin and the
  bootstrap this entry mandates below aborts immediately with
  `reviewed artifact changed after review: <path>`. `CUSTOMIZATION.md` step 4
  carries the same pair for the same reason. Otherwise
  stop installation/update and reacquire the reviewed release. Never regenerate
  hashes around a change you cannot account for. On an **already-bootstrapped**
  deployment, re-running `./scripts/bootstrap.sh` afterwards is required, not
  optional: it rebuilds the image so the edit actually reaches the gateway, and
  re-records `deployment-lock.json` against the new manifest — without which
  `backup.sh` aborts at its internal
  `record_images.py --validate-live` step with
  `differing: release_manifest_sha256`. (`--validate-live` is a
  `record_images.py` flag that `backup.sh` and `restore.sh` invoke themselves;
  it is not an argument you pass to those scripts.)
  Re-running `python3 -B scripts/record_images.py` alone re-affirms the lock but
  leaves the running image stale.

## 10. Known release limitations

- **The stuck-session watchdog, not `VC_MODEL_TIMEOUT_SECONDS`, decides when a
  slow model call dies — and from this release you cannot change that.** The
  harness aborts an agent run after a period with no *streaming* progress, and a
  prefill emits nothing until it completes, so it cannot distinguish a slow
  local model from a stalled provider. Through the `2026.7.1` base this package
  tuned it: `diagnostics.stuckSessionWarnMs` and `stuckSessionAbortMs` were set
  to `300000` and `960000`, above the 900 s maximum the validator allows for
  the per-call timeout, so `VC_MODEL_TIMEOUT_SECONDS` was the bound that
  actually fired. **`2026.8.1` retires both keys with no replacement.** The warn
  threshold is a fixed 120 s and the abort is derived from it as
  `max(300 s, 120 s x 3)` = **360 s**; there is no key, no environment
  variable, and no per-agent override. Leaving the keys in the config is not an
  option either — they are unrecognized, and the gateway exits 78 rather than
  starting.

  What that costs, stated plainly. A single model call that produces no
  streaming output for more than ~360 s is aborted regardless of
  `VC_MODEL_TIMEOUT_SECONDS`, so the 600 s Ollama floor this package documents
  can no longer be granted in full: it still governs the request as a whole,
  but it cannot rescue a cold prefill longer than the watchdog window. Measured
  on a CPU-only host under those same fixed thresholds: a legitimate 481 s cold
  prefill was aborted at 392 s (the threshold plus the sweep interval). The
  mitigations left are all host-side — keep the model resident so the prefill
  is paid once, use a smaller model or a shorter system prompt, or move to
  hardware that prefills inside the window. Do not
  grep for a sentence: the harness sets the error's name, message and code as
  three separate `Error` properties and never composes them into one line, so
  the token to search the gateway log for is the code `OPENCLAW_DIRECT_ABORT`.
  The watchdog's own line begins `stuck session recovery: ` and carries
  `action=abort_embedded_run`. Neither surface names the provider or the
  prefill, so the abort reads like a flake — which is exactly why it is
  recorded here rather than left to be rediscovered.
  `VC_MODEL_TIMEOUT_SECONDS` lives in `.env`,
  which the gate treats as runtime state: edit it and re-bootstrap.
  `config/openclaw.json` is both a hash-pinned reviewed artifact *and* a
  `manifest.json`-declared file, so an edit there takes three steps — re-pin the
  profile (`python3 -B scripts/init_customization.py --update-hashes`),
  regenerate the inventory (`python3 -B scripts/build_release_manifest.py`) or
  `verify_release.py` reports a permanent `hash mismatch` for it, and re-run
  `./scripts/bootstrap.sh`.
- **Channel plugins must stay under the harness's own extension scan root.** Not
  a limitation so much as a constraint that is easy to undo by accident, and it
  is load-bearing. The GHCR base image prunes the Slack, Teams, and Discord
  distributions, so `Dockerfile.openclaw` reinstalls them from the locked npm
  graph and then moves them into `/app/dist/extensions/<id>`, where the harness
  resolves them as `stock:<id>/…` with `origin: "bundled"`. The harness grants
  its keyed store only to a plugin that is bundled or a recorded trusted
  official install. Naming a channel in `plugins.load.paths` instead makes it a
  path/config origin, and every code path that reaches `openKeyedStore` then
  throws `openKeyedStore is only available for trusted plugins in this release`.
  Teams reaches it while *starting*: with the plugin path-loaded, the provider
  exited 40 ms after `[msteams] starting provider (port 3978)`, crash-looped
  through all ten auto-restarts, and never bound the port — while `bootstrap.sh`
  exited 0 and the container reported `healthy`. Slack and Discord carry the
  same call sites past authentication. `render_channel_config.py` therefore
  emits no load path for any channel, and
  `tests/v3/test_runtime_provider_and_context.py` asserts that. If a future edit
  reintroduces one, the symptom is a channel that never connects on a deployment
  that otherwise looks correct.
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
  fail-closed default. **There are two separate mechanisms here and disabling
  one does not disable the other.** Besides `cron.enabled: false`,
  `config/openclaw.json` sets `agents.defaults.heartbeat.every: "0m"`, which
  switches off the harness's own periodic *heartbeat* — a main-session agent
  turn that upstream runs **every 30 minutes by default** for the default agent
  whenever no heartbeat key is present (the pinned release resolves an absent
  key to enabled-at-`30m`, not to off). Without that key a shipped deployment
  would run an autonomous `vc-chief` turn against the configured model twice an
  hour, delivered nowhere, while every document here said it performed no
  autonomous execution. Confirm it on your deployment: the gateway logs
  `[heartbeat] disabled` at startup — `[heartbeat] started` means the key was
  lost and the render is stale. `tests/v3/test_runtime_provider_and_context.py`
  asserts the rendered value, and `workspaces/vc-chief/HEARTBEAT.md` is the
  operator-triggered checklist that mechanism would otherwise have run
  unattended. Autonomous source surveillance is available as a
  deliberate four-step opt-in. (1) Set `config/openclaw.json`
  `cron.enabled: true`. In the same edit set `cron.sessionRetention` to the
  firm's period (the completed session each cron run leaves behind; harness
  default `24h`, which fires sooner than the `session.maintenance.pruneAfter`
  of `30d` configured here), and add a `cron.failureAlert` block so a failing
  job is not silent — since this edit already re-pins the profile hash. The
  `2026.8.1` schema accepts exactly these keys under `cron`: `enabled`,
  `triggers.enabled`, `webhookToken`, `webhookSsrfPolicy`, `sessionRetention`,
  and `failureAlert` with `enabled`, `after` (consecutive failures, integer
  ≥ 1), `cooldownMs` (integer ≥ 0), `includeSkipped`, `mode` (`announce` or
  `webhook`), `accountId`, `channel`, and `to`. `cron` is a strict object, so
  anything else is a startup-fatal unrecognized key.

  Two keys earlier revisions of this section told you to set are **retired** in
  `2026.8.1` and must not be carried over. `cron.maxConcurrentRuns` is on the
  retired-tuning list. `cron.runLog.keepLines` is gone with the whole
  `cron.runLog` object: run history no longer lives in a `cron_run_logs` table
  at all — opening the state database migrates those rows into `task_runs` and
  drops the table — and retention is now a fixed upstream constant with no key
  (upstream's own migration note records it as 2000 runs per job). If a config
  carrying either key reaches `2026.8.1` the gateway refuses to start and the
  diagnostic tells you to run `openclaw doctor --fix`. **Do not.** That command
  is forbidden here (see §5.1) and, measured on this configuration, it exits 1
  without migrating anything. Delete the keys by hand instead. See
  `workspaces/vc-chief/vc/data_retention.md`. (2) Because that file is a
  hash-pinned reviewed
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
  native cron jobs. It is a commissioning action — validate the seeded jobs with
  `openclaw cron list` — and never performs autonomous outreach.

  What the script seeds, exactly:

  - **`vc-source-scan`** (always). A native cron job that sends `vc-chief` a
    standing-orders message in an **isolated** session; the chief then walks the
    due watchlist through the normal `source-scan` → research → `evidence-record`
    path for human review. It does not invoke the `source-scan` selector
    directly. Schedule and timezone default to `0 7 * * 1-5` / `Europe/Berlin`.
    Monday through Friday, successive fires sit 24 h apart — exactly the
    `daily` cadence boundary. `signal_source_is_due` requires the interval to
    have *fully* elapsed since the previous claim, and the claim stamps
    `last_scanned_at` with `clock_timestamp()`, later than the `now()` that
    judged the source due; so a source registered `--cadence daily` is skipped
    on the following weekday unless run-to-run timing jitter starts the scan
    later in the day than the previous claim landed. (The Friday-to-Monday gap
    is 72 h and clears it.) Before registering a `daily` source, give
    `VC_SCAN_CRON` a sub-daily schedule. The claim lands on the first fire more
    than 24 h after the previous one, so an evenly spaced schedule of period P
    settles at the smallest multiple of P strictly above 24 h: 25 h for an
    hourly `0 * * * *`, 36 h for a twelve-hourly one. `CUSTOMIZATION.md` states
    the general rule, and the approval that raising the frequency needs.
  - **`vc-heartbeat`** (only when `VC_HEARTBEAT_CRON` is set). A read-only
    health review per `workspaces/vc-chief/HEARTBEAT.md`.

  Both are idempotent through `--declaration-key`, so re-running the script on
  every deploy is safe. Its six tunables are read from the **process
  environment only** — `check_env.py` rejects every one of them in `.env` as an
  unknown key: `VC_SCAN_CRON`, `VC_SCAN_TZ`, `VC_SCAN_DELIVERY`,
  `VC_HEARTBEAT_CRON`, `VC_HEARTBEAT_DELIVERY`, and
  `VC_ALLOW_DISABLED_SCHEDULER`.

  The steps above are ordered, and the script enforces the order rather than
  trusting it: it reads `openclaw cron status --json` first and **exits 3
  without seeding** while the scheduler is disabled, because upstream `cron add`
  warns but still exits 0, so a job seeded into a disabled scheduler would be
  recorded as a success and never fire. Its refusal message repeats steps 1–3.
  `VC_ALLOW_DISABLED_SCHEDULER=1` seeds anyway, with a warning; use it only when
  you are deliberately staging jobs before enabling cron.

  Two behaviours to know before you run it. First, an empty delivery value is
  seeded as `--no-deliver`, not as upstream's default: omitting every delivery
  flag would make the pinned CLI announce to channel `last`, which an isolated
  session cannot resolve, and every run would be stamped `status=error` even
  though the research persisted. Set `VC_SCAN_DELIVERY="--announce --channel
  <c> --to <target>"` only if you want an internal digest delivered. Second,
  clearing `VC_HEARTBEAT_CRON` later does **not** remove a heartbeat an earlier
  run seeded; it keeps firing on its old cadence until you remove it with
  `openclaw cron rm <id>` (find the id with `openclaw cron list`).

## 11. Rebuilding after a Debian point release

`Dockerfile.openclaw` pins exact Debian package revisions (for example
`curl=7.88.1-10+deb12u15`) as a deliberate reproducibility contract. The
bookworm `main` pool keeps only the current revision of each package, so once
Debian ships a newer point release those exact pins are eventually removed from
`deb.debian.org` and the image build that bootstrap/update run (`docker compose
-f docker-compose.yml -p vc-lead-research-v3 --env-file .env build --pull
openclaw-gateway`) fails with ``E: Version '<version>' for '<package>' was not found``. The image build wraps the `apt-get
install` step to turn that otherwise-opaque failure into an actionable message.

There is a second, less obvious form of this. A pinned package can still be in
the pool while an **unpinned package it depends on** has moved — typically when
`bookworm-security` ships a coordinated update for a source package that
produces several binaries. apt then takes the newer dependency as its candidate
and refuses the older pinned name with:

```text
poppler-utils : Depends: libpoppler126 (= 22.12.0-2+deb12u2) but 22.12.0-2+deb12u3 is to be installed
E: Unable to correct problems, you have held broken packages.
```

This breaks a *fresh* build while every machine holding a cached image layer
keeps working, so it can go unnoticed. When it happens, pin the dependency
alongside its sibling and move both to the same revision — as this release does
for `libpoppler126` and `poppler-utils` — then re-run every release gate,
including `run_g6_image.py`, whose provenance assertions must list both names.
Verify a *fresh* build explicitly with `docker compose -f docker-compose.yml
-p vc-lead-research-v3 --env-file .env build --no-cache
openclaw-gateway`; a cached build proves nothing about the pool.
To rebuild the reviewed package set, point apt at a `snapshot.debian.org`
timestamp that still carries the pinned versions before building, and
**displace** the base image's own source list rather than adding beside it. The
`node:24-bookworm-slim` base ships `/etc/apt/sources.list.d/debian.sources`
pointing at `deb.debian.org`; left in place it gives apt a second source at the
same priority (500), and apt takes the higher version wherever the two differ.
Measured against `20260805T000000Z` with that file still present: `libnss3`
resolved to `2:3.87.1-1+deb12u4` from `deb.debian.org` rather than to the
snapshot's `2:3.87.1-1+deb12u3`, so the snapshot decided nothing. Add **both**
snapshot archives: the poppler pair sits at a `bookworm-security` revision,
which is never published into the `bookworm main` suite, so a main-only
snapshot cannot satisfy it however recent it is.

```sh
SNAPSHOT=20260825T000000Z   # the date the reviewed image was built
rm -f /etc/apt/sources.list.d/debian.sources
{ printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s/ bookworm main\n' "$SNAPSHOT"
  printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/%s/ bookworm-security main\n' "$SNAPSHOT"
} > /etc/apt/sources.list.d/snapshot.list
```

(add it inside the build, or bake it into a local Dockerfile overlay). The
timestamp must be at or after the date the reviewed image was built —
`docs/V3_RELEASE_EVIDENCE.md` records **2026-08-25** — not merely at or after
the last pin change, which is an earlier and different date. The gap is a
security revision: with `debian.sources` removed, `20260805T000000Z` resolves
`libnss3` to `2:3.87.1-1+deb12u3` while the reviewed image carries
`2:3.87.1-1+deb12u4`. That measurement is why the rule is the build date and
not the last pin change; the recipe's own timestamp above supplies the revision
the reviewed image carries.
`tests/v3/test_snapshot_recipe_currency.py` holds the `SNAPSHOT=` literal here
and in `Dockerfile.openclaw` to each other and to that recorded rebuild date, so
re-check it whenever the image is rebuilt. Resolving every pinned name is
necessary but not sufficient, and this is the trap: `20260805T000000Z` resolves
all ten pins and still installs `libnss3` one bookworm-security revision behind
the reviewed image, as measured above. A timestamp early enough to drop a
pinned version fails loudly, with the same ``E: Version '<version>' for
'<package>' was not found`` this section opens with — measured at
`20260731T000000Z`, which is before `libpoppler126=22.12.0-2+deb12u3` entered
the archive. (The `held broken packages` form above is the opposite condition,
an unpinned dependency moving *forward*, and cannot arise from an early
snapshot.) A timestamp that predates the build but still satisfies every pin
fails silently instead, in the thirty-eight added packages carrying no version
pin. Use the recorded build date, not the earliest timestamp that resolves. Editing
`Dockerfile.openclaw` to add the overlay makes `verify_release.py --pristine`
report a hash mismatch for that one file from then on, which is expected and
does not affect bootstrap or update. Alternatively, run the reviewed-release
process: bump the pins in `Dockerfile.openclaw`, then re-run every release gate
(offline, disposable Postgres, retrieval-scale, exact-image, and the real
deployment gate) and regenerate the manifest before shipping.

Be precise about what the pins contract. Ten package versions are fixed in
`Dockerfile.openclaw` and re-asserted against the built image by
`scripts/run_g6_image.py`. Comparing `dpkg-query` output between the base image
and the reviewed derived image, the apt step adds 45 packages, of which 7 carry
those pins; the other 38 — among them `libtiff6`, `libfreetype6`,
`libopenjp2-7`, `liblcms2-2` and `libnss3`, the imaging and TLS dependencies
poppler pulls in — carry no version pin, and nothing in the gates would notice
if the pool moved them. The `python3` and `python3-venv` pins are
python3-defaults metapackages, so the `3.11.2` they fix is that source's
revision and not the interpreter's: in `vc-lead-research:3.0.1`
`/usr/bin/python3` is a symlink to `python3.11` owned by `python3-minimal`,
while the interpreter binary `/usr/bin/python3.11` belongs to
`python3.11-minimal=3.11.2-6+deb12u8`, inherited from the digest-pinned base
image rather than pinned here. `scripts/run_g6_image.py` records why adding
`python3.11*` to the pin set is rejected. The snapshot timestamp is what reproduces that
remainder, which is why the recipe above is the reproducibility mechanism rather
than a fallback. A floating (unpinned) fallback for the ten is not offered
either: it would give up the one part of the apt step that is pinned and gated,
without making the other 38 any more determined.
