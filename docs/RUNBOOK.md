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
  research endpoints, the OpenClaw update channel (see below), and only the
  selected channel provider;
- loopback or private access to the gateway; a hardened TLS reverse proxy that
  exposes only `/api/messages` if Teams is selected; and
- a POSIX shell plus host `python3` **3.9 or newer** — the lifecycle scripts
  `bootstrap.sh`, `update.sh`, `backup.sh`, `restore.sh`, and
  `rotate_runtime_role.sh` shell out to it, and `check_customization.py`
  imports `zoneinfo`, which is 3.9+ (`migrate.sh` needs no python3; it uses
  POSIX utilities — `awk`, `sed`, `grep`, `cmp`, `command`, `mktemp`, and
  `sha256sum`/`shasum`). The backup and restore paths additionally call `tar`,
  `mktemp`, `tr`, `head`, `find`, `cp` and `chmod`, and `bootstrap.sh` — which
  §5.4 requires on the recovery host before `restore.sh` — also calls `cut`;
  all are present in a normal distribution base install, but check them
  explicitly if you build a minimal recovery host for the §5.4 drill, because
  `restore.sh` reaches `find` only *after* it has begun replacing production
  state;
- `openssl`, used to generate the six deployment secrets; and
- a non-root deployment operator with exclusive control of the package and
  `.env`.

**The OpenClaw update channel.** The gateway contacts its own update channel at
startup and logs, for example, `[gateway] update available (latest):
v2026.7.1-2 (current v2026.7.1). Run: openclaw update`. It is a version check
only — nothing is downloaded or installed, and the log line is informational.
It is listed here because an operator sizing a firewall allowlist would
otherwise not expect it. Two consequences:

- **Do not run `openclaw update`.** The image is pinned by digest in `.env` and
  `deployment-lock.json`; upgrading in place would break the pinned-digest
  contract and every provenance gate that depends on it. Upgrades go through
  `scripts/update.sh` with a reviewed release, per §8.
- If your egress policy denies it, the check fails and logs a warning. That is
  a supported configuration: nothing else in the deployment depends on it.

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
required. Retain the complete command transcript; to re-affirm or re-print the
recorded lock independently you may re-run the same recorder:

```sh
python3 -B scripts/record_images.py
```

The lock also records which image-baked artifacts the running image was built
from — the reviewed `workspaces/` tree, the trusted-context extension, the
exec-approvals seed and the dependency locks. Nothing bind-mounts those, so an
edit to a thesis, rubric, prompt or skill only reaches the gateway through a
rebuild. Assert at any time that a deployment reflects the current tree:

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
| 5.2 `openclaw_runtime` cannot create schema objects or temporary objects, and holds only the reviewed table/function grants | `tests/g4/test_database_contract.py` asserts, against a live database, that the role cannot create schema or temporary objects, that DDL as the runtime role fails, and a spot-check of eight table privileges across six tables and eight function grants. The *whole* 42-table grant matrix is enumerated offline instead, by `tests/v3/test_runtime_grant_enumeration.py` against `docs/SCHEMA.sql`: every table carries exactly one reviewed grant, none grants `DELETE`/`TRUNCATE`, the append-only tables grant no `UPDATE`, and the read-only trio stays read-only | — |
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

The restore drill in §5.4 is the one item no gate covers.

### 5.1 Image and configuration

- Prove the runtime OpenClaw version is exactly `2026.7.1` and record the image
  digest/ID.
- Prove Lobster resolves from `/opt/openclaw-runtime` at exact `2026.6.11`,
  Slack, Teams, and Discord resolve from the locked runtime graph at exact
  `2026.7.1`, and bundled Telegram is exact `2026.7.1`.
- Run the pinned OpenClaw configuration validation, `doctor`, secret audit, and
  deep security audit inside the exact image. Each runs through the gateway
  container, in the same form as §5.2 and §5.3:

  ```sh
  docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw config validate
  docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw doctor
  docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw secrets audit
  docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw security audit --deep
  ```

  A correctly configured shipped deployment still reports some findings, and
  §5.6's "a warning is not a pass" rule does not mean commissioning is blocked
  by them — it means each one must be dispositioned. The expected set below was
  recorded against a real deployment of this release; if you see a finding that
  is **not** on this list, treat it as a genuine deviation and investigate it.

  From `openclaw security audit --deep`:

  - `tools.exec.fs_tools_disabled_but_exec_enabled` — the `data-steward` exec
    permission: the reviewed design, see "Sandboxing and security design" in
    `README.md`. `data-steward` holds exec for exactly two allowlisted launcher
    paths (`config/exec-approvals.json`) and no filesystem tools, which is the
    combination this check flags generically.
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

  - one `Model "${VC_PRIMARY_MODEL}" specified without provider. Falling back to
    "openai/${VC_PRIMARY_MODEL}"` line per agent, and `openclaw models status`
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
    owner-scoped command for an owner ID to protect. Operator actions run
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
  - `update available (latest): v… (current v2026.7.1). Run: openclaw update` —
    the harness checks its own update channel at startup. See §2's egress list;
    do not run `openclaw update`, which would break the pinned-digest contract.

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
  it independently of the archives. The same `.env` must also carry an
  `OPENCLAW_STATE_ARCHIVE_MAX_BYTES` at least as large as the value in force
  when the backup was written (empty means the 2 GiB default): the backup
  records its effective bound in `BACKUP_MANIFEST` and `restore.sh` fails
  closed pre-mutation, naming the variable and the required minimum, if the
  target's bound is smaller. Size the target's `${TMPDIR:-/tmp}` for private
  restore staging at roughly the database dump + (2 × uncompressed state) +
  uncompressed inbox + (2 × uncompressed quarantine): the extracted trees must
  survive validation, and restore re-reads the state and quarantine tiers back
  from the deployment after mutation begins (`OPERATIONS.md`, "Rollback and
  restore"). Then run `./scripts/bootstrap.sh` so the
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
reviewed release. If the failure landed after the migrations applied, the
schema is already ahead of the recorded lock: a retry's pre-update backup
refuses rather than stamp the old version onto the new schema, so the valid
rollback target is the **first** attempt's recovery point, restored with the
package revision that matches it. Repeat all G8 checks affected by binary, schema,
configuration, provider, workflow, or model changes that affect the deployed
environment.

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
     the `(skills, agents, workflows)` triple. Several documents state it too:
     `docs/PRODUCTION_READINESS.md`, `docs/V3_RELEASE_EVIDENCE.md`,
     `evals/V3_EVAL_RESULTS.md`, `workspaces/vc-chief/vc/system_health.md`, and
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
     --entrypoint python3 openclaw-lead-research:3.0.0 \
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
   - the five documents listed in step 3, whose stated counts **nothing**
     checks. Grep for the outgoing number before you move on — with the shipped
     inventory that is `26`:

     ```sh
     grep -rn --include='*.md' '\b26\b' docs evals \
       workspaces/vc-chief/vc/RESOLVER.md \
       workspaces/vc-chief/vc/system_health.md \
       workspaces/shared-skills/resolver-check/SKILL.md
     ```

     `RESOLVER.md`'s inventory line is the one hit the validator does cover; the
     rest are yours.

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
  reconcile`, or any `rotate_runtime_role.sh` failure): the script has already
  stopped the gateway and CLI, and both database passwords in `.env` may now
  differ from what Postgres holds. Do not re-run the script blindly. Confirm
  Postgres is up (`docker compose -f docker-compose.yml -p
  openclaw-lead-research-v3 --env-file .env ps`), then check which credentials
  actually work by connecting as each role from the Postgres container
  **over TCP**:

  ```sh
  docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
    exec -e PGPASSWORD="<the password from .env>" postgres \
    psql -h 127.0.0.1 -U openclaw_owner -d openclaw -tAc 'select 1'
  ```

  The `-h 127.0.0.1` is load-bearing and this test is worthless without it. The
  pinned image's generated `pg_hba.conf` begins `local all all trust`, so a
  connection over the container's Unix socket — which is what plain
  `psql -U openclaw_owner` uses — succeeds with **any** password, including a
  wrong one. Only the `host` rules carry `scram-sha-256`
  (`POSTGRES_HOST_AUTH_METHOD` and `--auth-host` in `docker-compose.yml` set
  them), so TCP is the only path that actually tests the credential. A correct
  password returns `1`; a wrong one fails with
  `FATAL:  password authentication failed for user "openclaw_owner"`.

  If `.env` is ahead of the database, the owner password in `.env` is the one to
  correct. Once a working owner credential is in `.env`, re-run the script — it
  is idempotent. Only if neither credential authenticates over TCP should you
  restore from the last verified recovery point (§5.4); the database is the
  authoritative state and the gateway is stateless against it.
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
  slow model call dies — unless you keep the two in the right order.** The
  harness aborts an agent run after a period with no *streaming* progress, and a
  prefill emits nothing until it completes, so it cannot distinguish a slow
  local model from a stalled provider. With `diagnostics.stuckSessionAbortMs`
  unset the abort threshold is not a constant: the harness computes
  `max(300 s, stuckSessionWarnMs x 3)`, so the upstream defaults are 120 s to
  warn and **360 s to abort**, both below the 600 s minimum this package
  requires for `VC_MODEL_TIMEOUT_SECONDS` in Ollama mode — so at the defaults
  the package mandated a per-call budget the runtime would never grant.
  Measured on a
  CPU-only host: a legitimate 481 s cold prefill was aborted at 392 s with
  `AbortError: agent run aborted: code=OPENCLAW_DIRECT_ABORT`, a message that
  names neither the provider nor the prefill. `config/openclaw.json` therefore
  sets `diagnostics.stuckSessionWarnMs: 300000` and
  `diagnostics.stuckSessionAbortMs: 960000`, above the 900 s maximum the
  validator allows for the per-call timeout. **The shipped abort therefore
  already clears the whole legal range, so slower hardware needs no retuning;
  if you raise `VC_MODEL_TIMEOUT_SECONDS` within its 30–900 s range, keep
  `stuckSessionAbortMs` above it.** `VC_MODEL_TIMEOUT_SECONDS` lives in `.env`,
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
  native cron jobs. It is a commissioning action — validate the seeded jobs with
  `openclaw cron list` — and never performs autonomous outreach.

  What the script seeds, exactly:

  - **`vc-source-scan`** (always). A native cron job that sends `vc-chief` a
    standing-orders message in an **isolated** session; the chief then walks the
    due watchlist through the normal `source-scan` → research → `evidence-record`
    path for human review. It does not invoke the `source-scan` selector
    directly. Schedule and timezone default to `0 7 * * 1-5` / `Europe/Berlin`.
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
-f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env build --pull
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
-p openclaw-lead-research-v3 --env-file .env build --no-cache
openclaw-gateway`; a cached build proves nothing about the pool.
To recover a byte-reproducible build, point apt at a `snapshot.debian.org`
timestamp that still carries the pinned versions before building. Add **both**
archives: the poppler pair sits at a `bookworm-security` revision, which is
never published into the `bookworm main` suite, so a main-only snapshot cannot
satisfy it however recent it is.

```sh
SNAPSHOT=20260805T000000Z   # at or after this release's last apt-pin change
{ printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian/%s/ bookworm main\n' "$SNAPSHOT"
  printf 'deb [check-valid-until=no] https://snapshot.debian.org/archive/debian-security/%s/ bookworm-security main\n' "$SNAPSHOT"
} > /etc/apt/sources.list.d/snapshot.list
```

(add it inside the build, or bake it into a local Dockerfile overlay). The
timestamp must be at or after the last change to any pin in
`Dockerfile.openclaw` — currently **2026-08-03**, when `libpoppler126` and
`poppler-utils` moved to `22.12.0-2+deb12u3`. Re-check it whenever a pin moves,
and confirm the snapshot actually resolves every pinned name before relying on
it: an earlier timestamp reproduces the exact `held broken packages` failure
this recipe exists to cure. Editing `Dockerfile.openclaw` to
add the overlay makes `verify_release.py --pristine` report a hash mismatch for
that one file from then on, which is expected and does not affect
bootstrap or update. Alternatively, run the
reviewed-release process: bump the pins in `Dockerfile.openclaw`, then re-run
every release gate (offline, disposable Postgres, retrieval-scale, exact-image,
and the real deployment gate) and regenerate the manifest before shipping. A
floating (unpinned) fallback is intentionally not used because it would break the
exact-pin reproducibility contract.
