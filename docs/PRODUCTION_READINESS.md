# Version 3.0 production-readiness decision

Decision date: 2026-07-23 (final-audit session: every gate re-executed after the security/correctness remediation; supersedes the 2026-07-22 decision)
Live-model boundary restated: 2026-08-04, after five audit passes drove the agent layer against a real model (see "Exercised against a live model" below). The decision itself is unchanged; what changed is that the boundary is now drawn at model *judgement* rather than at model *contact*.
Package: `vc-lead-research`
Version: `3.0.1`
Decision: **Deterministic package and deployment path VERIFIED. The live-model path is exercised against a real model — resolution, provider reach, tool-call payloads, and the timeout/context/watchdog bounds. Behavioral certification remains BLOCKED: never run against a production-grade model. Not certified for autonomous decision quality until commissioned.**

## What changed since the 2026-07-21 decision

The prior decision certified this package "PRODUCTION READY" while three of its
workflows and its documented install were execution-verified broken, and while
its live-model gates were labelled PASS without ever running against a model.
The adversarial audit (retained in the project's internal audit archive)
established that. Subsequent sessions applied the fixes and this file now
reflects what was actually measured:

- **The install works.** The `bootstrap.sh` credential proof that previously
  aborted on the pinned Postgres image now completes (CR-002), execution-verified
  end-to-end by the new deployment gate.
- **All eighteen fixed workflows run.** The three that violated a database CHECK at
  their first persistence step are fixed (CR-003); four new workflows persist
  research intelligence and the memo autonomously (CR-001).
- **The execution blind spot is closed.** New suites run the real `.lobster`
  workflows and the real deployment end-to-end (CR-013).
- **Live-model gates are relabelled honestly.** Gates whose behavioral portion
  was never run against a model are BLOCKED, not PASS, per the frozen
  pre-commitment (`01_PRECOMMITTED_EVALS.md`: "Environment-dependent live gates
  may be reported BLOCKED, never PASS, without retained evidence").

Full detail is retained in the project's internal audit archive (excluded from the published package).

## Scope

This decision covers source and release cohesion, fail-closed configuration,
agent/tool authority, **eighteen** deterministic workflow boundaries (including the
new autonomous claim/evidence/contradiction/trajectory/memo persistence lane),
PostgreSQL state and migration contracts, verified multi-user context and bounded
preferences, entity resolution at the declared reference size, channel-document
security, configurable model/search rendering, dependency locking, backup
authenticity, restore preflight logic, controlled-evolution boundaries, and
release inventory.

The component-by-component basis is retained in the project's internal audit
archive (excluded from the published package).

## Release proof (executed 2026-07-23; last re-executed 2026-08-20)

Each figure in the table below is the measurement of a **2026-08-20**
re-execution against this tree — except where the cell quoting it names an
earlier run — and against the derived image rebuilt from it
with `docker build --no-cache --pull` on 2026-08-25, after that day's edits to the image-baked `workspaces/` files, `Dockerfile.openclaw` itself, and the host-side recovery-lifecycle scripts — not a
figure carried forward from the 2026-07-23 session. That re-execution was necessary rather than ceremonial: the
migrations, `vcops.py`, the eighteen `.lobster` workflows and
`Dockerfile.openclaw` — the file that defines the very image G6 and G8 build —
all changed after the original decision date. `docs/V3_RELEASE_EVIDENCE.md` and
`evals/V3_EVAL_RESULTS.md` carry the same note for the same run. The
offline-suites cell below names earlier runs in that way: alongside its current
total it narrates the superseded aggregates that earlier audit passes measured,
and each of those describes the tree it was taken on rather than this one.

| Proof | Result |
| --- | --- |
| Complete aggregate offline suites | 364 tests passed; 0 failed; 0 skipped; 30/30 offline checks pass (count re-verified 2026-08-20; the baseline was 231, and the runtime-provider/context regression tests that accompanied the context-window and Ollama-timeout floors added three more, moving it to 234; the heartbeat-disabled render assertion added on 2026-08-08 added one more, moving it to 235; the audit-invariant tests — evidence-document consistency and the erasure-gap enumeration — added on 2026-08-10 added eight more, moving it to 243; the fourteenth pass's mechanized-binding tests — documentation/tree consistency, runtime-grant enumeration, the customization count and coverage pins, the evidence-document growth-bridge and provenance guards, the workflow step-env allowlist, the dash-safe shell-escape guard, and the recovery state-bound and schema-ahead contracts — added nineteen more, moving it to 262; the fifteenth pass, across eight bindings — the skill-count pin and its RUNBOOK-recipe half, the ruff-inventory pin, the host-utility enumeration, the four quarantine-lane contracts, the run-history date binding, the step-reference command guard, and the documented-invocation checks — added twelve more, moving it to 274, while the SECURITY DEFINER REVOKE half tightened an existing test rather than adding one; the seventeenth pass added forty-one more, moving it to 315; and the eighteenth added forty more — the inbox-guard class-set equality and rotation-lock mirror pins, the two integrity checkers driven against each other over every (root, directory mode) pair, the governed-read envelope guarantee and its static companion, the wrapper-scope literal, the display-value straddle, the executed inbox-guard and package-path shell matrices, the interpreter-independent JSON-recursion pin, and the band-edge customisation-surface enumeration — moving it to 355; and the 2026.8.1 upstream upgrade added nine more — the upstream posture pins: the retired- and renamed-key sweep against the pinned upstream schema, the posture-pin value assertions, the five-hook trusted-context registration pin, the three-host egress enumeration, the Dockerfile-bound package-version binding, and the rendered-config posture-pin assertion that catches a pin dropped by the channel renderer — moving it to 364) |
| Disposable PostgreSQL G4 | 98/98 across seven suites (semantics 8, document security 19, database contract 11, helper CLI 23, workflow execution 10, research intelligence 19, source surveillance 8); migrations 001–018 applied and registered twice |
| Real deployment gate (G8) | PASS — `./scripts/bootstrap.sh` completes on the pinned images; the negative credential proof is rejected over TCP with no host trust rules remaining; fixed workflows run through real `vcrun`/Lobster inside the deployed gateway; an unchanged retry of a succeeded workflow returns an idempotent replay without re-executing, and the same key with changed arguments fails closed as `idempotency_payload_mismatch` leaving no new rows; an autonomous run leaves a non-empty knowledge base; teardown removes all state |
| Exact-image gate (G6) | PASS — 8/8 against the image rebuilt from this tree |
| Reference retrieval scale | PASS — 100k companies / 1m facts, all frozen thresholds met |
| Release integrity | Current manifest (`file_count` matches the packaged inventory), pristine inventory, workflow validation (18 workflows), Python/shell syntax, Ruff, and the ty type checker pass |
| Skills, agents, workflows | 26 skills, 12 agents, **18 workflows**, 0 findings (`validate_skill_system.py`) |

The local image digest is deployment-specific: `bootstrap.sh` rebuilds the
derived image from this tree and `record_images.py` records the resulting
digest in `deployment-lock.json` at install time.

The retrieval benchmark seeds deliberately **confusable clusters** — each fuzzy
case is a target plus four trigram-close distractor companies (mean 5 candidates
per case) — and scores **precision@1** (the top-ranked candidate must be the true
target) alongside recall, with a mean-candidate floor so the result cannot regress
to a no-confusables artifact. The real resolver scores recall = precision@1 = 1.0
by ranking each target above its look-alikes; a resolver that could not rank the
exact-ish match first would fail. This closes the former CR-013 dataset-artifact
item (audit P1-014/P1-015).

## Exercised against a live model (audit passes, 2026-08-04)

**The package's own gates still never invoke a model** — `verify_offline.py` has
no model step, and nothing below is a package gate. What follows was established
by audit passes outside the package boundary, driving a deployed stack against a
local Ollama model, and it is why the boundary above is drawn at model
*judgement* rather than at model *contact*:

- An agent turn resolves the configured model, reaches the provider, carries its
  tool payload, and returns. A real vendor completion still needs a credential;
  on a throwaway key the request path was proven to the provider's own
  `HTTP 401`.
- The bounds that govern a live call are measured, not assumed: the
  context-window floor, the Ollama per-call timeout floor, the harness
  stuck-session watchdog, and Ollama's silent input truncation at roughly half
  the served context. The watchdog measurement is now a **limitation** rather
  than a tuning input: `2026.8.1` retired the two keys that moved it, so its
  fixed 120 s warn / 360 s abort sits below the per-call timeout this package
  requires in Ollama mode and aborts a *healthy* call that prefills for longer.
  There is nothing left to set; see `README.md` and `docs/RUNBOOK.md` §10.
- Search results are fenced as untrusted at the provider boundary before the
  model sees them — the marking is applied in code, not by prompt convention.
- A channel provider starts and binds under a real configuration.

**This says nothing about output quality.** The models used were deliberately
small (sub-1B) — chosen to force mechanisms cheaply, not to produce useful
prose. Everything in the next section stays BLOCKED.

Detail is retained in the project's internal audit archive (excluded from the
published package).

## BLOCKED — never run against a production-grade model (not a package pass)

Per the frozen contract these are BLOCKED, not PASS:

- Model, search, channel, callback, and attachment-provider *behavior* — whether
  the model honours the untrusted-content fencing it is given, routes to the
  right specialist, and respects tool authority under adversarial input.
- Specialist output quality and memo decision-usefulness (semantic quality of the
  model's prose and citations — the actual VC deliverable). The package validates
  the *shape* of these outputs, never their semantic quality.
- Destructive recovery and credential-rotation exercises on a real target.
- Jurisdiction-, fund-, organization-, privacy-, and retention-specific review.
- Chosen-model quality/cost/context/tool-use qualification and target-host
  capacity/latency/monitoring/load qualification.

These are commissioning facts that depend on the operator's accounts,
infrastructure, policy, data, and legal context — and, for the model-behavioral
gates, on a production-grade model that this package boundary does not supply.

## Production operating boundary

The distributed package is deliberately inert: `PRIMARY_CHANNEL=none`, no
credentials, no cron, no harness heartbeat (`agents.defaults.heartbeat.every:
"0m"` — the upstream default is an agent turn every 30 minutes, and cron and
heartbeat are independent switches), no autonomous outreach. An operator must create a
mode-`0600` `.env`, retain an independent backup HMAC key, complete the
customization validator, and deliberately activate only the integrations it
needs.

The deterministic package and the deployment path are verified. Whether the
system's *autonomous decision quality* is fit for real capital allocation is
**not established by this package** and requires the BLOCKED live-model gates to
be run and reviewed. The `fact_promotion_policy` row controls autonomous
promotion: with `auto_promote=false` no `submitted_claim` becomes a
`verified_fact` without a human at the `evaluate-lead` gate. Which setting fits
a deployment is the operator's decision.

`scripts/verify_offline.py` is the unified package verifier. The complete release
proof uses:

```sh
python3 -B scripts/verify_offline.py \
  --with-g4-database \
  --with-schema-reference \
  --with-deployment \
  --with-retrieval-scale \
  --with-g6-image vc-lead-research:3.0.1
```

The runbook's live checklists and the BLOCKED gates above determine whether one
configured deployment may be activated for real decisions; they are not
retroactively redefined as package passes.

## DB-layer enforcement gaps found by the 2026-07-23 audit — fixed in place

The 2026-07-23 independent audit confirmed three defense-in-depth gaps where
the database boundary enforced less than its comments or callers implied.
Because no deployment of this package existed yet, all three were fixed
directly in the migration files pre-release (permitted by the release rule
"never edit one already deployed") and are proven at the SQL boundary by
dedicated G4 tests that call the database directly as the runtime role,
bypassing the helper's client-side checks:

- `016_approved_data_erasure.sql`: `consume_approval_and_erase_lead` now
  re-verifies the consumed approval's stored scope (and `lead_id` column,
  when set) against the erasure target inside the function; an approval for
  one lead can no longer erase a different lead even for a direct SQL caller,
  and the rejected attempt rolls back without burning the approval.
- `015_proposal_capture.sql`: a guard trigger rejects any INSERT born decided
  and any direct UPDATE that enters a decided proposal status; decisions pass
  only through the audited SECURITY DEFINER `decide_proposal(...)` function
  (exposed as the operator-gated `proposal-decide` helper command), and
  decided proposals are immutable to the runtime role.
- `012_research_intelligence_persistence.sql`: web-evidence corroboration
  independence is now keyed by **verified content hash**
  (`sources.content_sha256`), not by host — two sources corroborate a claim
  toward `verified_fact` only when their recorded content hashes differ, so two
  bare URLs (no recorded content hash) or two URLs with byte-identical content
  no longer count as independent corroboration, and disguised same-content URIs
  cannot count twice. The remaining residual is that the content behind that
  hash is still **model-supplied**: the package does not yet fetch the URL to
  compute the hash independently — a boundary that fetches and hashes the
  source itself remains the deferred CR-001 part-6 closure. It is backstopped
  by the human `evaluate-lead` gate, and `auto_promote=false` disables
  autonomous promotion entirely.

The 2026-07-23 final-audit session additionally closed, with execution-verified
G4/G5/G7/v3 tests: the build-context secret exclusion (`.dockerignore`), the
stage-first restore contract, pre-quiesce update preconditions, runtime-role
session time bounds (`statement_timeout`/`lock_timeout`/idle-in-transaction,
re-applied on every reconcile), model-lane watchlist boundary protection
(`source-watch` cannot re-enable a disabled entry — whoever disabled it,
including the model lane's own `source-unwatch` — nor reclassify or re-own
one), cross-lead document-provenance binding on `evidence-record`, the
operator-lane verified-fact source requirement and source trust-downgrade
refusal, quarantine containment for malformed OOXML, the approval-resume
run-budget and cancel workflow-binding in `vcrun-control`, the `vcrun`
one-JSON-object usage-error contract and kill-path reconciliation, the
renderer's lifecycle-env guard, fail-closed trusted-context attachment
blocking, and the `msteams` notification-provider spelling (migration 003).
