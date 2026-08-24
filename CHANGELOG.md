# Changelog

Notable changes to the Venture Capital Lead Research System, newest first. The
format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)
loosely — grouped entries under a dated version heading — with one deliberate
omission: this file carries no compare-link footer. 3.0.0 is the first published
entry, so there is no predecessor to compare it against. The footer goes in with
the second release, when a comparison exists to point at.

## Versioning, `VERSION`, and the tag

This project uses [semantic versioning](https://semver.org/spec/v2.0.0.html).
Two artifacts carry the number, and they deliberately do not move together:

- **`VERSION`** at the repository root names the **release**. It changes only
  when a new release is cut.
- **The annotated git tag `v3.0.0`** names the **commit that currently _is_
  that release**. Every audit or fix cycle ends by moving that tag to the new
  `HEAD` while `VERSION` stays at `3.0.0`, because such a cycle produces no new
  release — it corrects the one that already exists.

A moved `v3.0.0` is therefore not a re-release, and the tag is expected to move.
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

## [3.0.0] — 2026-08-24

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
> taken earlier fail `restore.sh --validate-lock`. There is no upgrade path
> across this boundary and none is offered; re-bootstrap from a fresh install
> and re-load the data by hand. [docs/RUNBOOK.md](docs/RUNBOOK.md) §1 records
> this in full, including why the change was taken and what remains exempt.

First public release. The date above is the day the published tree was finalised;
everything before it is private development history, which is why this file has
exactly one entry and no earlier version numbers. The dates on which each gate
was last measured are recorded in the evidence documents, not here — they move
independently of this heading and are maintained by
`scripts/set_evidence_execution_date.py`.

The Venture Capital Lead Research System 3.0 is an evidence-first, self-hosted
multi-agent system for venture-capital inbound and outbound lead research. It
uses [OpenClaw](https://github.com/openclaw/openclaw) `2026.7.1` as the agent
harness, PostgreSQL `17.10-bookworm` as the authoritative venture-data store,
and [Lobster](https://github.com/openclaw/lobster) `2026.6.11` for eighteen
fixed operational workflows. It runs entirely on the operator's own host and
the gateway's only unsolicited outbound call is a startup version check that
downloads and installs nothing, documented in `docs/RUNBOOK.md` §2 and safe to
deny. The downloaded package is deliberately unconfigured: it
holds no credentials, selects no channel, and cannot reach a model until an
operator supplies a reviewed configuration — a safe distribution default, not a
runtime limitation.

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
  113 `SPDX-License-Identifier` headers moved with it, as did the header
  constant that generates `docs/SCHEMA.sql`. `THIRD_PARTY_NOTICES.md` now tells
  a redistributor of the derived image to add `LICENSE` and `NOTICE` to the
  artifact they ship, because `.dockerignore` admits only build inputs and the
  image carries neither.
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
