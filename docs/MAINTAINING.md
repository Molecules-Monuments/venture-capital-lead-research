# Maintaining this package — Version 3.0

This document is the engineering standard for changing the Venture Capital Lead
Research System: what every Python edit owes before it counts as finished, what
a change to a file declared in the release manifest owes on top of that, and the
bar any audit of this package — a review round, a pre-release sweep, a
pre-publication check — is held to. Every rule below was added after something
got past the previous set of rules, so each one is written down together with
the reason it exists; a maintainer who understands the reason can tell a rule
that still earns its place from one that has been overtaken by a better check.
For the mechanics of forking, branching, and opening a pull request, see
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Every `.py` change must end green on both linters

Any change to any `.py` file in this repository — a one-line edit, a new file, a
deletion, a rename — is complete only when both checkers below exit `0`. If
either reports a failure, fix it and run both again. Repeat until both are
clean. A change that is described as done while either checker still fails is a
defect, not a judgement call.

```sh
VENV="../openclaw-v3-dev-venv"          # the disposable venv from README "Developer quick start"

"$VENV/bin/ruff" check . --exclude _internal --no-cache
"$VENV/bin/ty"   check . --python "$VENV" --python-version 3.11 --extra-search-path scripts
```

`$VENV` is the disposable virtual environment described in README's *Developer
quick start* section: created outside the package with `python3 -m venv
../openclaw-v3-dev-venv` and populated from the hash-locked
`requirements-dev.lock`. It lives outside the package on purpose — a virtualenv
inside the tree is undeclared content, and `scripts/verify_release.py
--pristine` reports it as such.

Both commands run from the package root. Check the exit status of each; neither
prints a non-zero status in a way a pipeline preserves, so do not pipe them
through `tail`/`head` when the result is what you need.

### Why each flag is there

- `--no-cache` on ruff is **mandatory**. Without it ruff writes `.ruff_cache/`
  into the package, and `scripts/verify_release.py --pristine` then reports an
  undeclared file — the operator-facing signal for tampering. `ty` writes no
  cache and needs no equivalent flag.
- `--exclude _internal` matches the release gate exactly
  (`scripts/verify_offline.py`). `ty` picks the same exclusion up from
  `.gitignore` on its own.
- `--python "$VENV"` is required for ty. Without it ty cannot resolve
  `psycopg`, `yaml`, `jsonschema`, `pypdf`, or `openpyxl`, and reports a wave of
  spurious unresolved-import errors.
- `--python-version 3.11` is the deployed floor: the derived image ships Debian
  Python 3.11 (the G6 gate records `3.11.2`) and `requirements-dev.lock` is
  compiled for 3.11+. Do not let ty infer the version from whatever interpreter
  is on `PATH`.
- `--extra-search-path scripts` mirrors what several suites do at runtime —
  `sys.path.insert(0, ROOT / "scripts")` before importing `check_env` as a
  first-party module. Without it ty reports an unresolvable import for code
  that runs fine.

### Fixing, not silencing

Treat every diagnostic as real until the code proves otherwise, and record which
one it was:

- **A true finding** is fixed in the code.
- **A false positive** is suppressed *narrowly* — `# noqa: <RULE>` for ruff,
  `# ty: ignore[<rule>]` for ty — on the specific line, with a comment saying
  why the checker is wrong. Never widen `ruff.toml`, never add a blanket
  ignore, and never suppress a whole file.
- If a fix would change runtime behaviour, that is a code change like any
  other: it needs the package's normal evidence, not just a green checker.

`ruff.toml` selects **295** rules across 22 linter families, not ruff's 59-rule
default. Every family in it was measured against this tree before being enabled,
and the five rule-level `ignore` entries each document a pattern this package
uses deliberately everywhere (`assert` in tests, list-argv `subprocess`,
`PATH`-resolved tooling, reviewed parameterised SQL, the atomic `/tmp` locks).

Do not widen it further as a way of "finding more", and do not add a family
without measuring it first — the families left out (`TRY`, `SLF001`, `T201`,
`PLW1510`, `PLC0415`, `SIM`, `RET`, `PERF`, `UP`, `FURB`, `ARG`, `Q`, `PTH`,
`INP`) were each excluded against counted evidence, not taste. Do not remove a
rule from `select` or add one to `ignore` to make a finding go away; fix the
finding or suppress that one line with a coded directive and a reason.

### What else a `.py` change usually requires

Green linters are the floor, not the finish line. A `.py` file that is declared
in `manifest.json` — which is every `.py` file outside `_internal/` — also needs:

```sh
python3 -B scripts/build_release_manifest.py     # re-pin the inventory
python3 -B scripts/verify_release.py --pristine  # must PASS
"$VENV/bin/python" -B scripts/verify_offline.py  # must PASS
```

`build_release_manifest.py` prints the delta it absorbs. Read it: if a listed
path is not a change that was made deliberately, that is an integrity finding
(`docs/RUNBOOK.md` §9), not a re-pin.

If the file lives in an image-baked source tree — `workspaces/`,
`runtime-extensions/vc-trusted-context/`, `runtime-packages/`, the
`BAKED_SOURCE_TREES` tuple in `scripts/record_images.py` — then on an
already-bootstrapped deployment re-run `./scripts/bootstrap.sh` and assert the
result with `python3 -B scripts/record_images.py --validate-baked-sources
deployment-lock.json` (run on the deployment host; the lock is written by
bootstrap and is not in the source tree). Those trees are copied into the image
and are not bind-mounted, so until the rebuild the three baked helpers —
`workspaces/vc-chief/vc/bin/vcops.py`, `vcrun.py` and `vcrun_control.py` — keep
running their previous version while every checker above stays green.

Note which world triggers that rebuild step: it is membership of a *source
tree*, not membership of the reviewed-artifact set. Gating it on the latter
would never fire for code at all: the inventory that would gate it holds
twenty hash-pinned reviewed artifacts, listed in `REQUIRED_REVIEWED_ARTIFACTS`
in `scripts/check_customization.py`, and not one of them is a `.py` path.

Separately, re-pin the profile too if the changed file is one of the
twenty hash-pinned reviewed artifacts:

```sh
python3 -B scripts/init_customization.py --update-hashes
```

That set is made of policy artifacts — thesis, rubric, sources, retention and
the like — so in practice this branch fires for a governed policy edit rather
than for a code edit, and both inventories have to be re-pinned when a single
change touches both worlds.

### Tooling provenance

`ruff==0.12.3` and `ty==0.0.65` are both pinned with hashes in
`requirements-dev.lock`, so the venv built by README's developer quick start
already carries them — there is nothing extra to install:

```sh
python -m pip install --disable-pip-version-check --require-hashes -r requirements-dev.lock
```

Both versions are therefore part of the reproducibility contract. To move
either one, edit `requirements-dev.in` and regenerate the lock with the command
recorded in its own header (`pip-compile --generate-hashes
--output-file=requirements-dev.lock --strip-extras requirements-dev.in`), then
re-run both checkers: a new release can change which diagnostics fire, and that
change belongs in the same reviewed commit as the version bump.

Both are additionally enforced by `scripts/verify_offline.py` as release gate
steps (`ruff` and `ty`), so a release cannot pass while either fails. Running
them by hand after each edit is still the rule — it is the fast feedback loop,
and the gate is the backstop, not a substitute for it.

Both gate steps resolve the checker from the gate's own interpreter before
falling back to `PATH`, so the pinned versions are what decide the result. If
either binary is missing, that step fails rather than being skipped.

## Updating a pinned dependency

Every lockfile in this repository is pinned by SHA-256 in `manifest.json`:
`requirements.lock`, `requirements-dev.lock` and
`runtime-packages/package-lock.json`. A change to any of them is therefore **two
edits in one commit** — the bump, and `python3 -B scripts/build_release_manifest.py`
to re-pin the inventory. A commit carrying only the bump fails the offline gate
on `release-pristine` and `manifest-current`, which is the contract working: an
unpinned dependency change is exactly what those checks exist to refuse.

This is why **Dependabot security updates are switched off** while **Dependabot
alerts are left on**. An automated bump PR can only ever change the lockfile, so
it cannot pass the required `offline-gates` check and cannot be merged as
opened. Alerts still surface a pin that picks up an advisory; a maintainer then
makes the bump and the re-pin together. Do not re-enable automated security
updates without also giving the bot a way to re-pin, or the Actions tab fills
with red PRs that no reviewer can make green.

`runtime-packages/` is additionally an image-baked source tree
(`BAKED_SOURCE_TREES` in `scripts/record_images.py`), so a change there does not
reach a deployment until the image is rebuilt. A dependency bump in that tree
carries the same obligations as any other baked-tree change: rebuild with
`docker build --no-cache --pull`, re-run `scripts/run_g6_image.py`, and move the
recorded rebuild date with `scripts/set_evidence_execution_date.py` — including
the two hand-edits that tool names but deliberately does not make.

Not every advisory is fixable here. Where an `@openclaw/*` plugin ships part of
its HTTP stack as **bundled dependencies** inside its own tarball, an npm
`overrides` entry does not move those copies; only an upstream release does.
Which plugins bundle is a property of each upstream release: at `2026.8.1`
`@openclaw/slack` and `@openclaw/discord` do, and `@openclaw/msteams` no longer
does. Read the `inBundle` flags in `runtime-packages/package-lock.json` rather
than assuming. When an advisory does land inside a bundled tree, record it
rather than leaving the alert unexplained.

`config/channel-plugins.lock.json` is a narrower, reviewed pin and not the
installer's lock — `runtime-packages/package-lock.json` decides the bytes. It
covers the four channel plugins, the `@clawdbot/lobster` CLI and, from `3.0.1`,
`@openclaw/duckduckgo-plugin`, which stopped being a base-image extension at
`2026.8.1`. `@openclaw/firecrawl-plugin` and `@openclaw/tavily-plugin` are
pinned in `runtime-packages/` only. The infrastructure contract suite
(`tests/infrastructure/test_infrastructure_contract.py`) binds each npm-installed
entry here to the npm lock and to `runtime-packages/package.json`, and
separately requires the four channels, so an entry may be added but none of the
four may be dropped.

## Auditing this package

Repeated audit passes established which checks keep working and which decay.
The count is deliberately not stated here: nothing enforces it, and an ordinal in
prose falls behind the history that contradicts it.
The rules below are binding for every future audit pass, review, or
pre-publication check of this package.

### Mechanized invariants — run them, never re-derive them

- **Evidence dates and counts are generated state, not prose.** Move the
  re-execution and image-rebuild dates in the four evidence documents only
  with `python3 -B scripts/set_evidence_execution_date.py <date>` (use
  `--check` to verify). Hand-editing them produced stale-date findings in two
  consecutive passes. `tests/v3/test_evidence_doc_consistency.py` binds the
  documented gate counts and the cross-document phrasings that carry them to
  fresh unittest discovery, so a drifted number fails the offline gate. Read
  that module's test names for the current list rather than restating it in
  this document — this enumeration has gone stale twice; when a count
  legitimately moves, update the documents to the measured value — never
  weaken the test.
- **Completeness claims need enumeration.** The erasure-gap list in
  `workspaces/vc-chief/vc/data_retention.md` is enforced by
  `tests/v3/test_erasure_gap_enumeration.py`: every table in `docs/SCHEMA.sql`
  carries exactly one disposition there. A table added to `docs/SCHEMA.sql`
  fails the gate until it is consciously categorized — and named in the
  retention document if it can hold subject data. The net closes only if the
  schema reference is current, which `verify_offline.py
  --with-schema-reference` proves — so regenerate `docs/SCHEMA.sql` with any
  migration change, as the manifest workflow already requires. Use the same
  pattern for any new prose that claims "only/every/all/none/complete": back it
  with a test that enumerates the world from the source of truth, or do not
  write it.
- **Migrations must apply over populated databases.** The
  `PopulatedUpgradePathTests` class in `tests/g4/test_database_contract.py`
  applies the series over a database that already holds rows, so a migration
  that UPDATEs or DELETEs a table an earlier migration's append-only trigger
  guards, or that derives a value violating a CHECK only pre-existing rows can
  reach, fails there instead of in the field. Its `fixtures` map is keyed by
  the three-digit prefix of the migration each fixture must survive, and each
  fixture is inserted immediately before that migration runs: `companies` rows
  before `006`, a `workflow_requests` row before `008`. A new backfill or
  derivation over an already-populated table adds a key to that map — a single
  split point can only ever populate one migration's inputs, so do not move
  one, and do not leave the backfill untested.

### Review lenses every audit pass must include

1. **Universal-quantifier audit**: grep the documentation for
   `only|every|all|none|exactly|complete|always|never` and verify each such
   claim by enumerating its world, not by spot-checking instances.
2. **State-space audit**: enumerate states the gates never construct
   (populated pre-migration databases are now gated; restore over an existing
   deployment, a crashed lifecycle lock, mid-upgrade interruption remain
   manual lenses) and walk each documented procedure against them.
3. **Newcomer cold-start**: follow README and RUNBOOK purely as written from
   a clean export; every referenced path, flag, and variable must exist.
4. **Cross-file contradiction sweep**: grep the load-bearing numbers, enums,
   and defaults across all documentation and diff their contexts.

### Process rules

- A finding is closed when its **class** is closed — by a test or gate, not
  by fixing the instance. A fix without an enforcing check is deferred
  recurrence.
- A zero-finding pass with the same lenses as the previous pass is weak
  evidence. The stopping criterion is consecutive clean passes under
  *rotated* lenses.
- Fixes made during an audit are the next audit's first suspects: re-review
  the pass's own diff against the same evidence bar before closing.

### Closing an audit or fix cycle: move the tag, keep the version

**Every audit or fix cycle ends by moving the current release's annotated tag —
`v` plus the contents of `VERSION`, today `v3.0.1` — to the new `HEAD`, with
`VERSION` itself unchanged.** This is not optional and not a judgement call.
Tags of superseded releases are never moved: `v3.0.0` still points at the
2026.7.1-based release and stays there.

```sh
python3 -B scripts/build_release_manifest.py      # read the delta first
python3 -B scripts/verify_release.py --pristine   # must PASS
git commit ...                                    # then, and only then:
git tag -f -a "v$(cat VERSION)" <new-HEAD> -F <annotation-file>
git for-each-ref "refs/tags/v$(cat VERSION)" \
  --format='%(objecttype) %(objectname:short) -> %(*objectname:short)'
```

`VERSION` names the **release**; the tag names the **commit that currently is
that release**. Audit and fix work does not produce a new release, so the
number does not move — but a tag left pointing at a commit whose defects have
since been fixed is a trap for anyone who checks it out expecting the release.
Between the ninth and fifteenth audit passes the tag sat six commits behind
`main`, spanning two blockers that would have broken every update on the
documented host.

Two conditions on the annotation:

- It must carry **this tag's own measured figures** — offline tests and checks,
  manifest file count, and the result of every heavyweight gate (G4/G6/G8) the
  cycle actually re-ran — taken from the run that just finished, never copied
  forward from the previous annotation. Verify each number against the gate
  output before writing it. A cycle that touches no input to one of those
  gates does not re-run it; say so by name and restate no figure for it, which
  is the only reading that does not force a copied-forward number.
- It must say what moved and why, so a reader can tell a re-tag of the same
  release from a new release.

Retagging in place is cheap only while the tag has never left the machine it
was made on. Once the repository has a remote that other people fetch from,
moving the tag is a deliberate force-push plus a note to anyone who may already
have fetched it — a clone that fetched the old object keeps it, so the two
sides disagree about what the release tag means until they are told. Plan the
announcement as part of the cycle rather than discovering it afterwards.
