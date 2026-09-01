# Changelog

Notable changes to the Venture Capital Lead Research System, newest first. The
format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
loosely — grouped entries under a dated version heading — with one deliberate
omission: this file carries no compare-link footer. It was left out at 3.0.0,
which had no predecessor to compare against, and it stays out for now: the
repository's release pages already carry the comparison and a hand-maintained
footer would be a second copy to keep true.

## Versioning, `VERSION`, and the tag

This project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).
Two artifacts carry the number, and they deliberately do not move together:

- **`VERSION`** at the repository root names the **release**. It changes only
  when a new release is cut.
- **The annotated tag `v<VERSION>`** — today `v3.0.1` — names the **commit that
  currently _is_ that release**. Every audit or fix cycle ends by moving that
  tag to the new `HEAD` while `VERSION` stays where it is, because such a cycle
  produces no new release — it corrects the one that already exists. Tags of
  superseded releases are left alone: `v3.0.0` still points at the 2026.7.1-based
  release and is not moved by work on 3.0.1.

A moved release tag is therefore not a re-release, and the tag is expected to move.
The convention exists because a tag left pointing at a commit whose defects have
since been fixed is a trap for anyone who checks it out expecting the release:
during development the tag once sat six commits behind `main`, spanning two
defects that would have broken every update on the documented host. Each move
rewrites the tag annotation with that tag's own measured gate figures, so
`git cat-file -p refs/tags/v3.0.0` tells you what the commit it points at
actually passed. [docs/MAINTAINING.md](docs/MAINTAINING.md) holds the rule and
the exact commands. The repository now has a remote, so each move of the tag is
a deliberate force-push plus a note to anyone who may already have fetched it —
plan that as part of the cycle rather than discovering it afterwards.

## [3.0.1] — 2026-09-01

Upstream base moved from OpenClaw `2026.7.1` to `2026.8.1`. This is a reviewed
release-engineering cycle, not an in-place update: the harness changed where it
stores exec approvals, retired configuration keys this package relied on, and
grew its unsolicited outbound surface. `VERSION` moves to `3.0.1` and a new
annotated `v3.0.1` tag is cut; `v3.0.0` stays where it is.

> [!IMPORTANT]
> **`scripts/update.sh` is the only supported path from 3.0.0, and the exec
> approval store changes underneath it.** `2026.8.1` reads the reviewed exec
> allowlist from the `exec_approvals_config` row of the OpenClaw state database
> rather than from `$OPENCLAW_STATE_DIR/exec-approvals.json`, and a leftover
> copy of that file makes every approvals read *and* write throw. The
> initializer now loads the image-baked seed into that row, deletes any such
> file (and the `.doctor-importing` claim file beside it) left in the state
> directory, and asserts they are gone. A deployment that skipped this step would come up with no
> allowlist at all — every Lobster workflow silently refused — while every
> offline gate stayed green, which is why the assertion reads the row back
> instead of the file.
>
> **The upgrade is one-way at the state volume, and the point of no return is
> the `openclaw-state-init` run — not the first gateway start.** That one-shot
> is a `service_completed_successfully` precondition of the gateway, and its
> approvals write and read-back move `state/openclaw.sqlite` from
> `PRAGMA user_version` 1 to 15; measured, a read-only `openclaw approvals get`
> under `2026.8.1` is enough on its own. A `2026.7.1` gateway then refuses that
> volume and exits 1 with `uses newer schema version 15; this OpenClaw build
> supports 1`. The `2026.7.1` **CLI does not**: it logs the same sentence as a
> migration warning, exits 0, and reports an empty allowlist with the effective
> exec policy at `security: "full"`. It fails open, so it is not evidence that a
> rollback worked. Once state-init has completed, restoring the pre-update
> recovery point is the only rollback — verify that recovery point is restorable
> before the update runs.

### Changed

- **Upstream harness `2026.7.1` → `2026.8.1`**, with the base image re-pinned by
  digest and the channel plugins moved to matching `2026.8.1` releases. The
  `duckduckgo` search extension is no longer bundled in the base image and is
  now a pinned npm plugin like Firecrawl and Tavily.
- **Exec approvals move to the state database.** The reviewed seed stays
  read-only and image-baked at `/opt/openclaw-seed/exec-approvals.json`, outside
  the state directory, and is loaded into `exec_approvals_config`. The harness's
  socket token now lives in that row, so the old rationale for leaving a
  writable JSON copy in the state volume is void and the documents that carried
  it have been corrected.
- **Retired configuration keys removed, and the pins that replace them added.**
  `diagnostics.stuckSessionWarnMs`/`stuckSessionAbortMs`,
  `cron.maxConcurrentRuns`, `cron.runLog`, `commands.useAccessGroups` and
  `tools.exec.timeoutSec` are gone from the schema; `agents.defaults.memorySearch`
  became `memory.search` and `skills.workshop.autonomous.enabled` became
  `.mode`. Every one of them was startup-fatal or a silent default flip, so the
  migration is by hand: `openclaw doctor --fix` remains forbidden here, and on
  this configuration it was measured to exit 1 without migrating anything.
- **MCP connector timeouts were renamed, and the unit changed with them.** If
  you copied `config/connectors.example.json` to `config/connectors.json` under
  `3.0.0`, that file has `"timeout": 30` and `"connectTimeout": 5` on each
  server. `2026.8.1` rejects both names, and the renderer injects your file
  verbatim, so the gateway exits `78` and crash-loops — after the update has
  already migrated the database. Convert the values as well as the keys, because
  the new names carry the unit: `"timeout": 30` becomes
  `"requestTimeoutMs": 30000` and `"connectTimeout": 5` becomes
  `"connectionTimeoutMs": 5000`. A straight rename would ask for a 30-millisecond
  request timeout, which the schema accepts. The rejected keys are named in
  `docker compose logs openclaw-gateway`.
- **Defaults pinned rather than inherited**, where `2026.8.1` moved them:
  `gateway.terminal.enabled: false` (upstream flipped it opt-in → opt-out,
  which would have exposed a browser-reachable shell inside the gateway
  container), `skills.workshop.autonomous.mode: "off"`,
  `plugins.entries["memory-core"].config.dreaming.enabled: false`,
  `memory.search.rememberAcrossConversations: false`,
  `agents.defaults.maxConcurrent: 3`, `agents.defaults.utilityModel: ""`,
  `agents.defaults.modelSelectionScope: "session"`, an explicit
  `agents.defaults.modelPolicy.allow`, and `telemetry.enabled: false`.
- **New `.env` keys, and a raised floor on one that already existed.**
  `2026.8.1` stages a private copy of the state database under `$HOME/.cache`
  before any process may write, so `OPENCLAW_INIT_CACHE_TMPFS`,
  `OPENCLAW_GATEWAY_CACHE_TMPFS` and `OPENCLAW_CLI_CACHE_TMPFS` are new and
  default to `512m`; `.env.example` carries the sizing rule and is the single
  place it is stated. `OPENCLAW_INIT_MEMORY_LIMIT` moves `256m` -> `768m`,
  because those staging pages are charged to the same memory cgroup and on a
  host without swap the memory limit binds before the cache does.
  `scripts/check_env.py` refuses anything below `128m` for that key, so a
  deployment carrying release `3.0.0`'s `64m` is told at pre-flight rather than
  OOM-killed after the migrations have run. A carried-forward `.env` that omits
  the three new keys is correct: compose supplies the same defaults.
- **Discord and Telegram outbound retry timing moved.** `2026.8.1` made both
  channel plugin schemas strict with no `retry` key, so the profiles' `retry`
  blocks had to go; re-adding them is startup-fatal. The attempt count is
  unchanged at three. The backoff cap moves `10s` -> `30s` and the jitter is
  halved, so a reply during a provider incident can arrive later than it did on
  `3.0.0`. Nothing is dropped.
- **Default model.** `openai/gpt-5.6` was removed from the `2026.8.1` OpenAI
  catalogue, so `.env.example` now ships `openai/gpt-5.6-sol` for both
  `VC_PRIMARY_MODEL` and `VC_FAST_MODEL`. `.env` is operator-owned and is not
  migrated, and `scripts/check_env.py` validates only the `<provider>/model`
  shape rather than the catalogue, so a deployment carrying the retired id
  forward keeps it until someone edits it by hand.

### Security and privacy

- **The unsolicited outbound surface is three hosts, not one.** The version
  check moved to `telemetry.openclaw.ai`; a model-catalogue refresh to
  `catalog.openclaw.ai` is new and runs every six hours; and a plugin-feed
  prewarm to `clawhub.ai` is new, unconditional, and **has no configuration
  switch of any kind**. The first two are pinned off. The third is deniable only
  by host egress policy, and denying it degrades nothing. `docs/RUNBOOK.md` §2
  enumerates all three with trigger, cadence, payload and off-switch, and §5.1
  names the log lines to expect under a deny.
- **`plugins.allow` is documented as what it is.** It was never a complete
  plugin boundary: the harness fills its default memory slot before consulting
  the allowlist, so `memory-core` loads regardless — on `2026.7.1` as well as
  `2026.8.1`. The claim has been corrected rather than the behaviour changed;
  the plugin stays loaded with `dreaming` pinned off, and unloading it is a
  separate reviewed change because the agent tool allowlists reference the tool
  names it supplies.
- **The erasure guarantee is stated as PostgreSQL-scoped.**
  `workspaces/vc-chief/vc/data_retention.md` now names what sits outside it,
  including an always-on full-text index of every message that `2026.8.1` adds
  with no key to disable it, and the archival-not-erasure semantics of session
  deletion.
- **The bundled-dependency wall came down, and the advisory count went to
  zero.** `@openclaw/msteams` stopped shipping `bundledDependencies` at
  `2026.8.1` — 139 bundled lock entries to none — so the entries
  `runtime-packages/package-lock.json` pins directly, which are the ones an npm
  `overrides` entry can actually move, went from 27 to 184. Measured with
  `npm audit --package-lock-only --omit=dev` under npm 12.0.2: the `3.0.0` lock
  reports **3 vulnerabilities** (1 moderate, 2 high) spanning 15 advisories —
  `axios` bundled inside `@openclaw/msteams` and `@openclaw/slack`, `undici`
  inside `@openclaw/discord` — and this one reports **0**. Advisory data is
  live, so re-run the command rather than trusting this line.

### Known losses

- **Stuck-session watchdog tuning is gone.** Warn is a fixed 120 s and abort a
  derived 360 s, with no key, so a model call that produces no streaming output
  for longer is aborted whatever `VC_MODEL_TIMEOUT_SECONDS` says. The
  mitigations left are host-side. This is upstream's removal, accepted rather
  than worked around.
- **Five `skill_workshop` actions are deliberately unreachable.** The tool grew
  from eight actions to fifteen; the image-owned guard is fail-closed and its
  allowlist did not change, so ten of the fifteen are refused: `apply`,
  `reject` and `quarantine`, which this design always refused; the two new
  lifecycle actions `restore_collection` and `complete`, which the same
  reviewed policy covers; and `read`, `prepare_patch`, `patch`, `evaluate` and
  `history` — the five this release deliberately leaves unreachable. Widening
  the allowlist is a behaviour change with its own review.

## [3.0.0] — 2026-08-25

> [!IMPORTANT]
> **A deployment created from a pre-publication revision cannot be upgraded in
> place.** Relicensing and renaming rewrote the first two lines — the licence
> identifier and the project-name header — of all eighteen `migrations/*.sql`
> files, so all eighteen SHA-256 digests moved. `scripts/migrate.sh` reconciles
> those digests against the append-only `schema_migrations` ledger before it
> applies anything, so on a database migrated by an earlier revision
> `bootstrap.sh`, `update.sh`, `rotate_runtime_role.sh` and `backup.sh` all fail
> closed, and the ledger cannot be repaired in place. The rename also re-derives
> the Docker volume names from the Compose project name, so Compose creates
> empty volumes and leaves the populated ones dangling — silently, because every
> script addresses its volumes through `docker compose -p`. Recovery points
> taken earlier are refused by `restore.sh`, whose lock validation step runs
> `record_images.py --validate-lock` against the recovery point. There is no
> upgrade path
> across this boundary and none is offered; re-bootstrap from a fresh install
> and re-load the data by hand. [docs/RUNBOOK.md](docs/RUNBOOK.md) §1 records
> this in full, including why the change was taken and what remains exempt.

First public release. The date above is the day the published tree was finalised;
everything before it is private development history, which is why no version
number earlier than this one appears below. The dates on which each gate
was last measured are recorded in the evidence documents, not here — they move
independently of this heading and are maintained by
`scripts/set_evidence_execution_date.py`.

The Venture Capital Lead Research System 3.0 is an evidence-first, self-hosted
multi-agent system for venture-capital inbound and outbound lead research. It
uses [OpenClaw](https://github.com/openclaw/openclaw) `2026.7.1` as the agent
harness, PostgreSQL `17.10-bookworm` as the authoritative venture-data store,
and [Lobster](https://github.com/openclaw/lobster) `2026.6.11` for eighteen
fixed operational workflows. It runs entirely on the operator's own host and,
**on the `2026.7.1` base this release pinned**, the gateway's only unsolicited
outbound call was a startup version check to `registry.npmjs.org` that
downloaded and installed nothing. That count is specific to this release: see
3.0.1 above, and `docs/RUNBOOK.md` §2 for the current enumeration. The
downloaded package is deliberately unconfigured: it holds no credentials,
selects no channel, and cannot reach a model until an operator supplies a
reviewed configuration — a safe distribution default, not a runtime limitation.

It is decision support, not an investor and not professional advice. Read
[README.md](README.md)'s scope and risk sections before deciding whether it
fits your process; several plausible-sounding capabilities are excluded on
purpose.

### The system

- Outbound discovery of startup candidates from reviewed public sources, and
  inbound lead requests through a private UI, the CLI, or one configured Slack,
  Microsoft Teams, Discord, or Telegram deployment.
- Governed PDF, PPTX, XLSX, and CSV intake from channel attachments or the
  authenticated host-operator lane, with content-addressed extraction and
  quarantine.
- Exact-first company identity resolution, with fuzzy matches offered as ranked
  review candidates that never authorize an automatic merge.
- Founder, traction, market, company-signal, and contradiction research that
  preserves URL, access date, and claim status rather than flattening them into
  prose.
- Evidence-linked qualification under a customizable fixed-denominator rubric,
  and internal memos written only from a frozen approved snapshot of what was
  actually supported.
- PostgreSQL persistence for venture entities, evidence, workflows, preferences,
  evaluations, memos, approvals, and audit, over migrations `001`–`018`.
- Typed chief-to-specialist delegation and return contracts, each delegation
  carrying a budget, expected schema, positive test, falsifier, and stop rule.
- Eighteen fixed Lobster workflows for bounded, persistence-oriented operations,
  driven through `vcrun`'s exact argument contracts.
- OpenAI by default, native local Ollama, and reviewed custom HTTPS model
  providers; a generic `web_search`/`web_fetch` surface with optional DuckDuckGo,
  Firecrawl, or Tavily routing.
- Per-user, bounded VC Chief preferences learned only under verified identity.
- A documented lifecycle: `bootstrap.sh`, `update.sh`, `backup.sh`,
  `restore.sh`, and `rotate_runtime_role.sh`, with format-3 recovery points
  whose checksum manifest is authenticated by a dedicated HMAC-SHA-256 key held
  outside the recovery point.
- Controlled evolution: operator-reviewed proposal drafting with a
  model-narrated shadow-test protocol (not machine-executed in 3.0); only an
  operator-controlled repository release can activate a proposal.

### Authority boundaries

The working rule is that models may propose, while deterministic boundaries
validate, record, or refuse:

- Models interpret and propose; they do not directly mutate authoritative
  venture state.
- A user, message, or attachment cannot assert its own identity or file path. A
  deployment-owned trusted-context extension signs those facts for the turn,
  with HMAC, expiry, exact schema, path scope, principal, and one-operation
  replay records.
- Lobster controls step order and continuation; PostgreSQL and `vcops` decide
  whether a business mutation is valid.
- Task Flow tracks agent and task operation; it does not prove that a lead,
  evaluation, preference, approval, or memo committed.

### Evidence recorded for this release

Measured on the tree this release was cut from:

| Gate | Result |
| --- | --- |
| `verify_offline.py` | PASS — 355 tests, 30/30 base checks (31 with `--with-schema-reference`) |
| `run_g4.py` (disposable PostgreSQL 17) | PASS — 98 tests across 8 checks, migrations applied twice |
| `run_g6_image.py` | PASS — 8/8 against `vc-lead-research:3.0.0` |
| `verify_release.py --pristine` | PASS — 342 declared, 342 verified |
| `ruff` 0.12.3 / `ty` 0.0.65 | exit 0 |

The live deployment gate (`run_g8_deployment.py`) was **not re-run for the
publication cycle**; its last recorded execution and the exact boundary between
package evidence and deployment evidence are in
[docs/V3_RELEASE_EVIDENCE.md](docs/V3_RELEASE_EVIDENCE.md) and
[docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md). Passing gates
certify the software and its install; they do not certify model-behavioral
decision quality, jurisdiction or fund policy, or capacity on your host. Those
remain the operator's commissioning work.

### Changed for open-source publication

These changes were made to publish the release and touch no application
behavior, with the one breaking exception recorded in the note at the top of
this entry.

- **Relicensed** from the BSD Zero Clause License to the **Apache License,
  Version 2.0**, Copyright 2026 Molecules & Monuments GmbH. Apache-2.0's
  express patent grant is worth more to a system assembled from other people's
  harnesses, plugins, and runtime images than the shorter licence's brevity. All
  `SPDX-License-Identifier` headers moved with it — 112 in the published tree,
  every file the convention in `CONTRIBUTING.md` covers and no other — as did
  the header constant that generates `docs/SCHEMA.sql`.
  `THIRD_PARTY_NOTICES.md` now tells a redistributor of the derived image to
  add `LICENSE` and `NOTICE` to the artifact they ship, because `.dockerignore`
  admits only build inputs and the image carries neither.
- **Renamed** to the Venture Capital Lead Research System 3.0. The published
  name drops the harness it happens to be built on: that name belongs to the
  upstream dependency, not to this system. The project-derived identifier is now
  `vc-lead-research`, which moved the Compose project (`vc-lead-research-v3`),
  the derived image tag (`vc-lead-research:3.0.0`), four Docker volume names,
  two host lock directories, and the two npm package names. Everything naming
  the upstream project — `openclaw_runtime`, `openclaw-gateway`,
  `openclaw-state`, `OPENCLAW_IMAGE`, the `openclaw` database, every
  `@openclaw/*` dependency — keeps its name unchanged.
- **Added** `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1,
  with only its Enforcement section rewritten), `NOTICE`, and
  `docs/MAINTAINING.md`, which carries the engineering rules that govern
  changing this package in maintainer voice.
- **Added** the `.github/` intake surface — bug, documentation, and question
  issue forms that ask for what a reproduction here actually needs, plus a
  pull-request template — and an `offline-gates` CI job that runs the
  deterministic offline matrix on pull requests to `main`, pushes to `main`, and
  manual dispatch. It installs `requirements-dev.lock` under `--require-hashes`
  so the pinned `ruff` and `ty` decide the result, and it carries no path filter
  on purpose: several offline tests bind documented counts back to the tree, so
  a documentation-only change can legitimately fail it.
- **Added** this changelog, and a module docstring to the fifteen test modules
  that had none. Each says what its suite binds and which class of defect it
  exists to prevent; no test logic changed.
- **Removed** the numbered response windows from `SECURITY.md`. The policy
  promised acknowledgement within 7 days and assessment within 30; two
  maintainers working alongside other commitments could not keep them, and a
  reporter plans around a promise. It now states what actually happens, states
  plainly that there is no service-level agreement, and tells a reporter whose
  report has gone unanswered that they may disclose on their own timetable
  without this project's agreement.

### Earlier history

There is no 2.x entry in this file, and there will not be one. Version 2 was a
prior internal system — the baseline this release was designed against and
assessed in `02_BASELINE_ASSESSMENT_AND_CHANGE_GATE.md` — not a published
release of this repository. Inventing dates and version numbers for it would
give a reader something to diff against that never existed.
