# Version 3.0 release evidence

Date: 2026-07-23 (final-audit session; supersedes the earlier 2026-07-23 and 2026-07-22 evidence)
Last full re-execution: **2026-08-10** — see "Count re-verification" below. Every *count* in this document is that run's measurement; the one latency figure the gates produce is treated separately under "Image digests — regenerate at deployment", because it is a property of the measuring host rather than of this tree.
Package version: `3.0.0`
Status: **Deterministic package + deployment path VERIFIED; live-model behavioral gates BLOCKED (not run). See `PRODUCTION_READINESS.md` for the exact boundary.**

Count re-verification: the suites grew across the remediation sessions that
followed the 2026-07-23 evidence, so every count below is the count this tree
actually produces rather than a carried-forward figure. **The full matrix was
last re-executed on 2026-08-10**, against this tree and against the derived
image rebuilt from it with `docker build --no-cache --pull` on **2026-08-10**,
after that day's edits to one image-baked `workspaces/` file and one
migration. The image is
therefore derived from exactly this tree rather than reused. Earlier in the same
session `bootstrap.sh` also built the image during the live channel exercise,
and the G8 deployment gate's own bootstrap built and tore down another. The gates: `verify_offline.py`
(**235 tests, 25/25** base checks), and each opt-in gate individually —
`run_g4.py` (**88/88** across seven suites, migrations 001–018 applied
twice on PostgreSQL 17.10), `run_g6_image.py` (**8/8**, against an image rebuilt from this tree with
`docker build --no-cache --pull` and again against the one `bootstrap.sh`
builds during the deployment gate; both load `vc-trusted-context` from
`/opt/openclaw-extensions`), `run_g8_deployment.py` (**PASS** — five checks
end-to-end, with a clean teardown leaving no containers, volumes, or runtime
files), `run_retrieval_scale.py` (**160/160** cases, comfortably inside the
frozen 250 ms p95 threshold — see the note on that figure below),
`verify_release.py --pristine`,
`build_release_manifest.py --check`, and `generate_schema_reference.py
--check`. That re-execution also re-proves the pinned `deb12u3` poppler pair
still installs from the live Debian pool. For reference, `c72d8b9` — the last
commit before the channel-setup rewrite — measures 210 offline tests across
these same suites, so everything from that rewrite through the pre-publication
audit remediation added twenty-five in total; the per-suite figures in the table
below are authoritative and sum to the aggregate.

## 2026-07-23 final-audit evidence

The final-audit session re-verified every claimed fix from the prior sessions
first-hand, then applied and execution-verified a further security/correctness
remediation: build-context secret exclusion (`.dockerignore`), the stage-first
restore contract (every backup member staged with a single read before HMAC
verification; no post-verification reads of the operator-writable backup
directory), pre-quiesce update preconditions, `vcrun` one-JSON-object usage
errors and kill-path reconciliation, the renderer's lifecycle-env guard,
fail-closed trusted-context attachment blocking, runtime-role session time
bounds, watchlist boundary protection (`source-watch`), cross-lead
document-provenance binding (`evidence-record`), the verified-fact source
requirement and trust-downgrade refusal (operator lane), quarantine containment
for malformed OOXML, approval-resume run-budget and workflow binding, the
proposals INSERT-forgery guard (migration 015), content-addressed corroboration
independence (migration 012), and the `msteams` provider spelling (migration 003).
Every gate below was executed after those changes:

| Surface | Result | Command |
| --- | ---: | --- |
| Offline verification (all suites, ruff, ty, shell syntax, fixed workflows, skill system, manifest currency, pristine) | **PASS — 235 tests, 25/25 checks** | `python3 -B scripts/verify_offline.py` |
| Disposable Postgres hard gate | **PASS — 88/88** across seven suites, migrations 001–018 applied twice | `python3 -B scripts/run_g4.py` |
| Exact-image gate against the image rebuilt from this tree | **PASS — 8/8** (provenance, workshop guard, all five channel schemas, unknown-field fail-closed) | `python3 -B scripts/run_g6_image.py --image openclaw-lead-research:3.0.0` |
| Real deployment gate (bootstrap → negative-auth proof → live fixed workflows → replay/tamper semantics → teardown) | **PASS** | `python3 -B scripts/run_g8_deployment.py` |
| Reference retrieval scale (100k companies / 1m facts) | PASS, all frozen thresholds met | `python3 -B scripts/run_retrieval_scale.py` |
| Pristine release inventory | PASS — `verified_files` == `declared_files`, 0 errors | `python3 -B scripts/verify_release.py --pristine` |

The DB-layer boundaries are proven at the SQL level by G4 tests that call the
database directly as the runtime role: a cross-lead erasure attempt with a
valid approval for a different lead fails and rolls back without burning the
approval; a proposal cannot be born decided nor decided by direct UPDATE — only
the audited `decide_proposal` lane succeeds, exactly once, with an audit event;
web sources corroborate a claim only by **distinct verified content hash**
(`sources.content_sha256`), never by host — two URLs with no recorded content
hash, or two URLs returning byte-identical content, do not corroborate no matter
how many registrable hosts they span (migration 012's promotion predicate; the
`registrable_host()` helper survives only as a reviewed utility and gates
nothing, and `test_14_web_corroboration_is_content_addressed_not_host_based`
executes this); a document artifact bound to one lead cannot corroborate another
lead; and a disabled watchlist entry cannot be re-enabled, reclassified, or
re-owned from a model-reachable lane — the guard is on the disabled state, not
on who set it, so a model lane cannot undo even its own `source-unwatch`.

This evidence records what was executed. Live provider/recovery exercises,
model-behavioral quality, organization-specific policy, and target-host capacity
are BLOCKED (never run against a production-grade model) or
deployment-commissioning activities, not package passes. The live-model
*mechanism* — model resolution, provider reach, tool payloads, and the
timeout/context/watchdog bounds — was separately exercised against a real model
by audit passes outside this package boundary; see
`docs/PRODUCTION_READINESS.md`, "Exercised against a live model". No gate below
invokes a model.

## Passing evidence (executed 2026-07-23; last re-executed 2026-08-10)

| Surface | Result | Reproducible command |
| --- | ---: | --- |
| Agent schemas/contracts | 42/42 | `python3 -B -m unittest discover -s tests/contracts -p 'test*.py' -v` |
| Version 3 providers/context/orchestration/customization/skill system | 56/56 | `python3 -B -m unittest discover -s tests/v3 -p 'test*.py' -v` |
| Exact skill/agent/router/workflow inventory | 26 skills, 12 agents, **18 workflows**, 0 findings | `python3 -B scripts/validate_skill_system.py` |
| Retrieval policy contracts | 7/7 | `python3 -B -m unittest discover -s tests/retrieval -p 'test*.py' -v` |
| Infrastructure contracts | 29/29 | `python3 -B -m unittest discover -s tests/infrastructure -p 'test*.py' -v` |
| G6 image/channel contract (offline) | 4/4 | `python3 -B -m unittest discover -s tests/g6 -p 'test*.py' -v` |
| Fixed workflow/runner boundary | 48/48 | `python3 -B -m unittest discover -s tests/g5 -p 'test*.py' -v` |
| Recovery/release lifecycle | 28/28 | `python3 -B -m unittest discover -s tests/g7 -p 'test*.py' -v` |
| Scoring/helper semantics | 6/6 | `VCOPS_HELPER=workspaces/vc-chief/vc/bin/vcops.py python3 -B -m unittest discover -s tests/g4 -p 'test_semantics.py' -v` |
| Document security | 15/15 | `VCOPS_HELPER=workspaces/vc-chief/vc/bin/vcops.py python3 -B -m unittest discover -s tests/g4 -p 'test_document_security.py' -v` |
| Data/helper/Postgres hard gate | **88/88** | `python3 -B scripts/run_g4.py` |
| Real deployment gate | PASS | `python3 -B scripts/run_g8_deployment.py` (or `verify_offline.py --with-deployment`) |

The aggregate deterministic offline suites pass 235 tests with no failures or
skips (25/25 offline checks). The per-suite rows above sum to that total. The G4 runner created a disposable PostgreSQL 17
cluster, applied and registered migrations **001–018** twice, and — in addition
to the prior trusted-context/preference/idempotency/approval/document coverage —
now executes the **real `.lobster` workflow files end-to-end** against the live
database (`test_workflow_execution.py`, including `evaluate-lead`'s approved and
denied paths) and the **autonomous research-intelligence lane**
(`test_research_intelligence.py`: claims land as `submitted_claim` with
provenance; promotion to `verified_fact` fires only through the deterministic
corroboration predicate; untrusted uploads never corroborate; a model cannot
assert a status; memos persist only from the frozen approved snapshot and cannot
cite outside it; the memo read-back is confidentiality-gated; concurrent writes
respect the lead-scoped dedup).

The new deployment gate ran the real `./scripts/bootstrap.sh` to completion on
the pinned images, re-proved that an invalid password is rejected over TCP with
no host trust rules remaining, executed fixed workflows (including the three
previously-dead ones plus `evidence-record`) through real `vcrun`/Lobster inside
the deployed gateway, confirmed the autonomous run left a non-empty knowledge
base, and tore the deployment down.

## Image digests — regenerate at deployment

The local image ID is host-specific: `bootstrap.sh` rebuilds
`openclaw-lead-research:3.0.0` from this tree and `record_images.py` records
the resulting digest in `deployment-lock.json` at install time. The G6 gate was
re-run on 2026-08-10 against an image rebuilt from this tree with `docker build
--no-cache --pull` (8/8), and the retrieval-scale gate was re-run on 2026-08-06,
2026-08-07, 2026-08-08, 2026-08-09 and 2026-08-10 (160/160 cases every time).

**The retrieval p95 is the one figure in this document that is not a stable
property of the tree**, so it is deliberately not quoted as one. It is a latency
measured on whatever host and under whatever load the gate happened to run, and
repeated runs of *this* tree have produced an overall p95 anywhere between
roughly 40 ms and 90 ms without any code change. What is reproducible, and what
the gate actually asserts, is the frozen threshold set: overall p95 **at most
250 ms**, fuzzy precision@1 and recall **at least 0.90** each, and a mean
candidate count **at least 1.5**. Every run recorded for this release has
cleared all four by a wide margin, scoring 1.0 on both fuzzy metrics. Treat
a specific millisecond figure the way this section treats an image ID — a
property of one host, regenerated locally — and re-measure on the deployment
host rather than inheriting a number from here.

The retrieval benchmark now seeds deliberately **confusable clusters** — each
of the 100 fuzzy cases is a target company plus four trigram-close distractor
companies, so a fuzzy query surfaces multiple competing candidates (mean 5 per
case) rather than a name with no near-neighbours. The gate measures
**precision@1** (the top-ranked candidate must be the true target, not a
look-alike) and recall, and asserts the mean candidate count exceeds 1.5 so the
1.0 result cannot regress to the old no-confusables artifact. The real resolver
scores recall = precision@1 = 1.0 by correctly ranking each target above its
four confusables; a resolver that could not rank the exact-ish match first
would fail precision@1. This closes the former CR-013 dataset-artifact item
(audit P1-014/P1-015).

Recovery points use backup format 3. `BACKUP_AUTHENTICATION` authenticates the
exact checksum manifest with a dedicated HMAC-SHA-256 key transferred outside the
recovery point. Restore verifies this envelope before accepting inventory or
mutating state. (These are executed by `tests/g7` at the source-contract level; a
real destructive target restore is a BLOCKED commissioning exercise.)

## BLOCKED — never run against a production-grade model

- Live model/search/channel *semantics*, callbacks, reply delivery, and channel
  document behavior — the judgement a capable model exercises, not the
  mechanism that carries it, which is covered in `docs/PRODUCTION_READINESS.md`.
- Specialist output quality and memo decision-usefulness (semantic quality of the
  model's prose and citations). The package validates output *shape*, not
  semantic quality.
- A destructive restore and credential-recovery exercise on the target.
- Jurisdiction-, fund-, organization-, privacy-, and retention-specific policy.
- Capacity, cost, latency, and quality qualification on chosen models and host.

The package is inert until an operator supplies reviewed configuration. Passing
the deterministic and deployment gates certifies the software and its install;
it does not certify the model-behavioral decision quality, which the BLOCKED
gates above must establish.
