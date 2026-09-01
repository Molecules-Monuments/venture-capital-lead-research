# Version 3.0 customization guide

This package is a publishable reference system, not a universal investment
policy. It ships inert and must fail closed until an accountable operator has
replaced the sample fund profile, reviewed the security/privacy controls, and
passed the relevant evals.

## Required publication workflow

1. Run `python3 -B scripts/init_customization.py`. It writes
   `config/customization-profile.json` from the example and pins the twenty
   `review.reviewed_artifacts` hashes; it marks nothing as reviewed.
2. Replace every placeholder, set only reviewed booleans to `true`, record the
   stable reviewer/change record, and set `status` to `reviewed` last.
   `check_customization.py` gates exactly twenty of the profile's booleans. The
   twenty-first, `channels.live_acceptance_completed`, is your own record that
   the live channel matrix in `docs/CHANNELS.md` has passed, and is deliberately
   ungated: that matrix can only be exercised with the channel already selected
   and running, so requiring it here would make channel activation unreachable.
   `docs/RUNBOOK.md` §5.6 is its enforcement point, not this validator.
3. Apply the corresponding edits in the files below. The JSON profile records
   the decision; it does not silently rewrite policy.
4. Re-pin both inventories: the twenty reviewed artifacts among the files
   below are hash-pinned in two places, and every other packaged file you
   edit is pinned in `manifest.json` alone:

   ```sh
   python3 -B scripts/init_customization.py --update-hashes
   python3 -B scripts/build_release_manifest.py
   python3 -B scripts/verify_release.py --pristine
   ```

   Skipping this leaves `verify_release.py --pristine` and the
   `manifest-current` gate failing on your own deliberate edits.
5. Run `python3 -B scripts/check_customization.py
   config/customization-profile.json .env`. Passing the `.env` path is what
   binds the reviewed timezone, model/provider IDs, search/fetch selection,
   channel selection and approver destination IDs to the exact deployment
   environment; validating the profile alone is not a publication gate.
6. **If you have already bootstrapped, re-run `./scripts/bootstrap.sh`.** Policy
   artifacts are baked into the derived image, not read from this tree at
   runtime, so until you rebuild, the deployment keeps applying the previous
   version of everything you just edited. See
   [Policy edits reach the deployment only through a rebuild](#policy-edits-reach-the-deployment-only-through-a-rebuild).
7. Rebuild the routing, scoring, retrieval, specialist, memo, privacy, and live
   channel fixtures affected by the changes. Passing old fixtures against a new
   thesis is not evidence.
8. Run all offline gates and the applicable live acceptance matrix before
   selecting a channel or production traffic.

## Policy edits reach the deployment only through a rebuild

`Dockerfile.openclaw` copies `workspaces/`,
`runtime-extensions/vc-trusted-context/`, `config/exec-approvals.json`,
`runtime-packages/` and `requirements.lock` into the derived image and makes
them read-only; `docker-compose.yml` bind-mounts none of them. That is
deliberate — a model lane must not be able to rewrite its own agent contracts,
skills or helper entry points, and the exact-image gate (G6) can only prove
content the image owns — but it has one consequence you must know:

> Your thesis, exclusions, rubric, source lists, prompts and skills are a
> **build-time snapshot**. Editing them on the host re-pins cleanly, passes
> `check_customization.py`, and passes `verify_release.py --pristine`, while the
> running gateway continues to serve the previous version. Nothing fails.

`./scripts/bootstrap.sh` is the remedy and needs no extra knowledge: it rebuilds
the image, recreates the gateway, and re-records `deployment-lock.json`. It is
safe to re-run on a live deployment.

The lock records which bytes the running image was built from, so the drift is
detectable rather than silent. To assert that a deployment reflects your
reviewed policy:

```sh
python3 -B scripts/record_images.py --validate-baked-sources deployment-lock.json
```

`PASS` means the running image was built from this exact tree. Otherwise it
names the rebuild. `init_customization.py --update-hashes` and
`check_customization.py` also report the condition when a recorded deployment
predates your edit — as a required next step, not a failure, because a tree
ahead of its deployment is the normal state between the edit and the rebuild.

This applies to every row in the tables below whose files live under
`workspaces/`, plus `runtime-extensions/vc-trusted-context/`, `runtime-packages/**`
and `requirements.lock`.

It does **not** apply to `.env`, `config/openclaw.json` or the channel configs.
Those are rendered into the runtime-config volume, and the initializer replaces
that volume's copy unconditionally on every `bootstrap.sh` and
`rotate_runtime_role.sh` (`compose run --rm --no-deps openclaw-state-init`), so a
rendered change always reaches the gateway.

`config/customization-profile.json` is on neither path. Nothing renders it and no
container mounts or reads it: it is a host-side review record consumed only by
`check_customization.py`, which every config-applying lifecycle script
(`bootstrap.sh`, `update.sh`, `restore.sh`, `rotate_runtime_role.sh`) runs
before it mutates anything. `backup.sh` alone runs without it, so an
unvalidated profile never blocks taking a recovery point. So editing the profile changes what the validators will accept, never
what the deployment does at runtime — `approvals.stable_approver_ids` is an
attestation rather than a runtime allowlist (identity is bound to
`VCOPS_OPERATOR_ID`), and `approvals.expiry_minutes` is a reviewed record that
nothing reads (the enforced lifetime is `--expires-minutes`, default 60).

`config/exec-approvals.json` is digested with the image-baked set — a change to it
is detected — but it is **not customizable**, and a rebuild would not apply one:
`tests/infrastructure` pins its exact two-entry allowlist, the initializer's `jq`
assertion pins its reviewed keys, and once the file exists in the state volume the
initializer deliberately does not replace it (OpenClaw may maintain its own socket
token there). Editing it fails the offline gate. See the
`DO_NOT_CUSTOMIZE_DIRECTLY` table.

## `MUST_CUSTOMIZE` files

| Decision | Files | How to customize and re-evaluate |
|---|---|---|
| Organization, operator intent, timezone | `workspaces/vc-chief/USER.md`, `.env` (`TZ`), customization profile | State the product objective, fund strategy, reporting style, stable deployment owner, and authority limits. Re-run orchestration and channel tests, then `./scripts/bootstrap.sh` if already deployed (`USER.md` is image-baked). |
| Thesis, stage, sector, geography, check/ownership targets | `workspaces/vc-chief/vc/thesis.md`, `exclusion_criteria.md`, `prequalification.md`, profile | Replace the sample text with your firm's own mandate, exclusions and prequalification bar. The routing and scoring cases under `tests/g3` and the eval JSONL files are hash-pinned examples; after editing any governed artifact, re-pin with `python3 -B scripts/init_customization.py --update-hashes` and, on an already-bootstrapped deployment, re-run `./scripts/bootstrap.sh` — these files are image-baked, so until the image is rebuilt the chief keeps applying the sample thesis. |
| Scoring criteria, weights, missingness, thresholds | `workspaces/vc-chief/vc/scoring-rubric.md` and its machine JSON `workspaces/vc-chief/vc/scoring-rubric.v3.json`, `tests/g3`, scoring evals | The shipped weights, bands and gates are examples; the software does not assess their predictive quality. Evidence quality and coverage are separate inputs, and unknown is never scored as negative. The policy version is frozen at `3.0` for this release: customize weights, bands and gates only, never the version (see "Generated and coupled files"). **The recommendation band boundaries are re-encoded in a database CHECK, so changing them means changing the database too, and how you do that depends on whether you have bootstrapped yet.** Before your first `bootstrap.sh`, edit the CHECK in `migrations/007_scoring_readiness_gate.sql` directly — no migration ledger exists yet, so nothing is bound to its checksum. The CHECK is reproduced in the generated `docs/SCHEMA.sql` in PostgreSQL's own normalised form (`(50)::numeric`, `ANY (ARRAY[...])`), so you will not find it there by searching for the migration's text and must not try to patch it by hand -- regenerate it (`python3 -B scripts/generate_schema_reference.py`, needs PostgreSQL 17 `initdb`, `pg_ctl`, `psql` and `pg_dump` on `PATH` — the server package, not `postgresql-client-17` alone) before re-pinning, or `verify_offline.py --with-schema-reference` fails on the stale reference. (`manifest.json` records both files, so re-pin the manifest afterwards as step 4 requires, or `verify_release.py --pristine` reports your own edits as an integrity mismatch.) **After bootstrap, never edit 007** (or any applied migration): `migrate.sh` compares each file against the recorded checksum and fails closed on every later `bootstrap`, `update` and `rotate_runtime_role` run. Add a new numbered forward migration instead that drops and recreates the CHECK with your bands, then regenerate `docs/SCHEMA.sql` and the manifest. Until the rubric and the CHECK agree, `evaluate-lead` fails at persistence and the G4 gate fails. `workspaces/vc-chief/vc/governance_lint.md` also refers to the band edges, so review it against your bands. **One choice of edges is refused outright, and re-cutting the fixtures does not rescue it**: `display_5` rounds `final_100 / 20` to one decimal, and an integer edge falls inside a display value — rather than on its boundary — unless it is congruent to 3 mod 4 (verified over all 99). If EVERY interior edge you choose is 3 mod 4 — the natural "shift the shipped edges up by one" choice, 51/67/83, is exactly that — then every display value maps to a single band, the rubric's "deliberately no display-scale equivalent" claim stops holding, and `verify_offline.py` fails the g4-semantics suite no matter how the fixtures are cut. Move any one edge off 3 mod 4 (51 to 50 or 52, say), or accept that your deployment CAN read a band off a display value and amend the rubric's prose and the three display-value artifacts together. **Three further shipped artifacts state the shipped edges outright and no gate catches them**, so update all three with your own: `workspaces/vc-chief/vc/eval_fixtures.md` (its evaluation checklist names every boundary — 0, 49.999, 50, 65.999, 66, 81.999, 82, 100 — and the display-window straddle), `tests/g3/README.md` (the notation example `[0, 50)`, `[50, 66)`, `[66, 82)`, `[82, 100]` and the `2.5`/`3.3`/`4.1` straddle values, which move with your edges) and `docs/DATA_MODEL.md` (its interval-to-band table and the `[82, 100]` override sentence). `migrations/001_initial_v2.sql` and `migrations/004_domain_contract_hardening.sql` also contain the edge arithmetic but must NOT be edited: both are superseded — 004 drops 001's inline CHECK and 007 drops and recreates 004's `evaluations_score_band_check` — and editing an applied migration makes `migrate.sh` fail closed on every later run. **A WEIGHTS-ONLY change needs the fixtures re-cut too, and its failure names something else entirely.** `tests/g4/semantic_cases.json` passes its own copy of the criterion weights to the helper, which refuses any caller whose weights differ from the reviewed rubric. Measured: swapping two criteria's weights — leaving the total unchanged, the most conservative edit this row authorises — leaves the g4-semantics suite red with eleven errors, every one of them `rubric_weight_mismatch: caller weights do not match the reviewed rubric`, which names neither the rubric nor the fixture. Re-cut that file's weights alongside any weight change, and recompute the `expected_score` of every case in it, since those totals are derived from the weights. **Two fixtures encode the band edges and both are replayed by the offline gate**, so re-cut both onto your own `final_100` edges or `verify_offline.py` fails on the g4-semantics suite: `tests/g3/scoring_boundary_cases.jsonl` (one row per edge; `tests/g4/test_semantics.py` re-derives every row's expected band through the shipped helper) and **`tests/g4/semantic_cases.json`**, whose `scores` array carries six edge-bearing cases — `pass_upper_edge`, `watch_lower_boundary`, `watch_upper_edge`, `research_lower_boundary`, `research_upper_edge` and `high_priority_lower_boundary` — each pinning an `expected_score` AND an `expected_recommendation` at a shipped edge. Measured: moving the edges to 40/60/80 and re-cutting only the g3 file still leaves g4-semantics red with three failures naming `pass_upper_edge`, `watch_upper_edge` and `research_upper_edge`. Two of the files this row sends you to — `tests/g3/scoring_boundary_cases.jsonl` and the rubric's machine JSON `workspaces/vc-chief/vc/scoring-rubric.v3.json` — are among the twenty hash-pinned reviewed artifacts, so re-pin the profile afterwards (`python3 -B scripts/init_customization.py --update-hashes`) on a bootstrapped deployment, or the next lifecycle run fails closed on your own edit. `tests/g4/semantic_cases.json` is NOT one of the twenty; it is caught by the g4-semantics suite instead, as measured above. The rubric is image-baked, so re-run `./scripts/bootstrap.sh` on a deployed system. |
| Sources and outbound discovery | `primary_sources.md`, `active_sourcing.md`, `passive_sourcing.md`, `inbound_sources.md`, `third_party_connectors.md`, `workspaces/outbound-scout/USER.md` | Record stable URL/provider, purpose, allowed data, cost/rate/terms, expected signal, owner, and stop rule. Which sources you admit, and on what terms, is your decision; check the provider's terms of use with your counsel if in doubt. |
| Research depth, cost, and models | `research_depth.md` **and the mirroring numbers in `workspaces/shared-skills/research-depth-control/SKILL.md` (retune both together)**, `.env` (`VC_MODEL_PROVIDER`, `VC_PRIMARY_MODEL`, `VC_FAST_MODEL`, common model limits), profile | Select OpenAI, native Ollama, or one reviewed HTTPS custom provider. Benchmark tool calling, JSON, context, prompt injection, quality, privacy, latency, and cost on frozen suites. For Ollama, validate the private endpoint, pulled models, host capacity, and restart behavior. Equal model IDs are allowed only when deliberately reviewed. The shipped tier split (PRIMARY: `vc-chief`, `market-mapper`, `memo-writer`; FAST: the other nine, including the scoring gate and the sole DB writer) is a cost-first sample, not a benchmarked optimum. `.env` defines the two model IDs; which agent uses which is the `"model"` field on each agent in `config/openclaw.json` (a hash-pinned reviewed artifact — re-pin both inventories after editing it). |
| Search and fetch provider | `.env` (`VC_WEB_SEARCH_PROVIDER`, `VC_WEB_FETCH_PROVIDER` and selected key), `primary_sources.md`, `third_party_connectors.md`, profile | Keep the generic agent tool contract. Choose `auto` only with direct OpenAI, or explicitly select a native provider: `duckduckgo` (keyless), `firecrawl`/`tavily` (keyed) — all three present only because `runtime-packages/package.json` pins their plugin packages, so keep those pins; as of the `2026.8.1` base the image ships **no** bundled search provider, DuckDuckGo included — or `brave`/`perplexity`/`exa`/`searxng`/`parallel-free` (not pinned — pin the plugin package + rebuild, or render fails closed). Selecting `firecrawl` for search also makes it the fallback the fetch lane uses when local extraction returns nothing, unless you pin a fetch provider; see the search table in `README.md`. Review coverage, ranking, processor terms, retention, rate/cost, egress, failure behavior, and source quality. A provider switch requires research regressions and exact-image/config validation. |
| Approvers and governed actions | `approval-policy.md`, channel overlays/IDs in `.env`, profile | Use stable authenticated IDs, separation of duties, target/action limits, expiry, and atomic consumption. Test reject, expiry, mismatch, replay, and rollback. Never replace IDs with display names. `approvals.expiry_minutes` records the reviewed decision only; nothing reads it. The enforced lifetime is the `--expires-minutes` argument to `approval-request` (default 60). |
| Privacy, lawful basis, confidentiality, retention | `trust_boundaries.md`, `storage_tiers.md`, `data_retention.md`, `document_intake.md`, profile | These files hold whatever purpose, lawful basis, allowed fields, audience, processor, retention, deletion, legal-hold and restore policy your firm determines; the software stores and applies that text but does not evaluate it. Ask your counsel if any of it is in doubt. The shipped values are examples to edit. |
| Channels, users, attachments, notification policy | `.env`, channel overlay, `channel_policy.md`, `document_intake.md`, `notification_policy.md`, `docs/CHANNELS.md`, profile | Begin with `PRIMARY_CHANNEL=none`; use one provider, exact destination IDs, and a reviewed comma-separated stable-user list. Set a measured 1–50 MiB transport cap. Test per-peer sessions, principal preference isolation, signed path scope, all four supported documents, hostile/unsupported media, provider replay, and restart. Teams Graph/SharePoint channel files are a separate privileged design. This release does not authorize proactive outreach. |
| User preference memory | `AGENTS.md`, `trust_boundaries.md`, `data_retention.md`, preference workflows/helper/migration/tests, profile | Keep the five-key closed schema unless undertaking a versioned schema migration. Define retention/deletion response, explain explicit versus three-event inference, test user isolation/group denial/forget cutoff/replay, and never use preferences as evidence, permission, or scoring input. |
| Agent roster/routes/skills | `config/openclaw.json`, `workspaces/vc-chief/vc/RESOLVER.md`, affected agent `AGENTS.md`, shared `SKILL.md`, canonical schemas | Preserve one channel-facing chief, no specialist delegation, bounded steward exec, and no external writes. `skillify` may create a complete pending Workshop candidate; only an operator repository release may activate it. Update schemas, dependency fixtures, allowlists, documentation, manifest, and release inventory together. A new persona without distinct information is not a useful agent. |
| Memo and reporting | `workspaces/shared-skills/memo-writing/SKILL.md`, memo schema/template/evals, operator intent | Preserve claim-evidence mapping, case/countercase, cruxes, falsifiers, next diligence, snapshot hash, and recommendation parity. Length and audience are yours to set. |

## `REVIEW_AND_CONFIRM` files and limits

- document limits and supported file policy;
- allowed-user count and channel attachment transport limit;
- user-preference retention and deletion response;
- operating hours and quiet hours;
- web-search provider: set `VC_WEB_SEARCH_PROVIDER` in `.env` (and `search.provider`
  in the profile) to any native provider — `duckduckgo` (keyless), `firecrawl`,
  `tavily` are ready in the image; `brave`, `perplexity`, `exa` (each keyed),
  `searxng` (keyed by `SEARXNG_BASE_URL`), and `parallel-free` (keyless) are also
  native but **non-bundled** — each additionally requires its plugin package
  pinned in `runtime-packages/package.json` (+ `package-lock.json` regen and
  image rebuild). What checks the pin is `render_channel_config.py`, which reads
  the declared dependency set and fails closed when a selected provider has no
  plugin declared. The exact-image (G6) gate does **not** cover it: its
  `image-package-provenance` check compares a fixed ten-package inventory
  (`EXPECTED_PACKAGES`, itself pinned by `tests/g6/test_image_gate_contract.py`)
  and renders all five profiles at `VC_WEB_SEARCH_PROVIDER=auto`, so an eleventh
  plugin is never read either way. Re-run G6 after the rebuild regardless — it
  still validates the rest of the image — but the only thing that proves your
  plugin is actually installed is starting the gateway with that provider
  selected. Extending G6 to cover it means editing both the gate and that
  contract test. The package
  ids are `@openclaw/brave-plugin`, `@openclaw/perplexity-plugin`,
  `@openclaw/exa-plugin`, `@openclaw/searxng-plugin`, and — for `parallel-free`
  — `@openclaw/parallel-plugin`. Add the one you need at an exact version,
  in `runtime-packages/`, regenerate the lock with the **two-pass** procedure below (a single
  `npm install --package-lock-only` yields a 333-entry lock that `npm ci
  --omit=dev --omit=peer` then rejects with 26 `Missing: ... from lock file`
  lines, and under npm 12 pass 1 additionally needs `--allow-remote=all`):

  ```sh
  npm install --package-lock-only --omit=dev --allow-remote=all
  npm install --omit=dev --omit=peer --ignore-scripts --no-audit --no-fund
  rm -rf node_modules   # pass 2 reifies ~27,000 files; --pristine fails without this
  ```

  `--allow-remote=all` belongs to pass 1 only, and is an artefact of
  `--package-lock-only`. npm 12 defaults `allow-remote` to `none`, and in
  lock-only mode that default refuses the plugin tarballs even though their
  URLs are the configured registry's own: measured on this lock, pass 1 exits
  `EALLOWREMOTE` on
  `https://registry.npmjs.org/@openclaw/discord/-/discord-2026.8.1.tgz` under
  both `none` and `root`, so `all` is the narrowest value that works. Pass 2
  and the image's `npm ci` both complete at the `none` default; do not carry
  the flag into `.npmrc`.

  Then rebuild the image, and re-run the G6 gate; that
  reviewed, pinned, lock-regenerated rebuild *is* the audited dependency
  process the table below refers to. Selecting a
  non-bundled provider **without** pinning its plugin now fails closed at
  `render_channel_config.py` (every lifecycle path runs it) with an actionable
  message, rather than rendering a config that references a plugin the image
  does not contain. (`parallel-free` is the keyless variant of the parallel
  plugin; the paid `parallel` provider, which needs `PARALLEL_API_KEY`, is not
  offered.) Set the matching key (`BRAVE_API_KEY`, etc.) only for the selected provider;
- third-party data connectors (Crunchbase/PitchBook/etc.): copy
  `config/connectors.example.json` to `config/connectors.json` and list each as a
  native MCP server with `grant_to` the research specialists; keys stay as
  `${VAR}` references. The three example vendors' keys (`CRUNCHBASE_API_KEY`,
  `PITCHBOOK_API_KEY`, `DEALROOM_API_KEY`) are pre-wired into the gateway/CLI
  environment — set them in `.env`. A connector using a different variable name
  needs a one-time commissioning edit to `check_env.py` and `docker-compose.yml`
  (see `third_party_connectors.md`);
- source freshness and evidence-confidence thresholds;
- automated source surveillance: the watched-source registry (`signal_sources`,
  managed via the `source-watch`/`source-unwatch` fixed workflows) and its scan
  cadence. `source-scan` is operator-triggerable at any time; to make
  surveillance **autonomous**: set `config/openclaw.json` `cron.enabled: true`,
  set `cron.sessionRetention` to the firm's retention period and add a
  `cron.failureAlert` block in the same edit (harness default retention `24h`;
  run-log retention is no longer configurable — `cron.runLog` and
  `cron.maxConcurrentRuns` are retired in `2026.8.1` and are startup-fatal if
  left in the file; see `data_retention.md` and `docs/RUNBOOK.md` §10 for the
  full accepted key set), re-pin **both** inventories as
  step 4 requires — record the new artifact hash
  in `config/customization-profile.json` (`review.reviewed_artifacts` plus the
  change record) *and* regenerate `manifest.json` with
  `python3 -B scripts/build_release_manifest.py`, because the file is declared
  in both and skipping the second leaves `verify_release.py --pristine`
  reporting your own edit as a permanent integrity mismatch — re-run
  `./scripts/bootstrap.sh` so the change
  reaches the gateway's rendered runtime config (the gateway never reads the
  host file directly), and then seed the schedule with
  `./scripts/schedule_jobs.sh` (idempotent; tunable
  via `VC_SCAN_CRON`/`VC_SCAN_TZ`/`VC_SCAN_DELIVERY`, optional
  `VC_HEARTBEAT_CRON`/`VC_HEARTBEAT_DELIVERY`, plus the
  `VC_ALLOW_DISABLED_SCHEDULER` escape hatch — the script otherwise refuses to
  seed while the gateway's scheduler is still disabled). These six are read from
  the environment of the `schedule_jobs.sh` invocation only — they are not
  `.env` keys, and `check_env.py` rejects them there as unknown variables.
  It uses OpenClaw's native cron to send `vc-chief` a fixed scan instruction on
  the chosen schedule. A source becomes due once its cadence interval has fully
  elapsed since the previous scan claimed it: `signal_source_is_due` tests
  `last_scanned_at < now() - <cadence interval>`, so at exactly one interval the
  source is not yet due, and the claim stamps `last_scanned_at` with
  `clock_timestamp()`. A cron firing at the same period as a source's cadence
  therefore lands within a second of that boundary and can skip the cycle; set
  `VC_SCAN_CRON` to fire more often than the shortest cadence you register.
  The shipped default `0 7 * * 1-5` sits on that boundary Monday through
  Friday against the shortest registerable cadence, `daily`, so registering a
  `--cadence daily` source without making `VC_SCAN_CRON` sub-daily is the case
  this rule is about; `docs/RUNBOOK.md` §10 works out the interval a shorter
  scan period actually produces.
  Per `approval-policy.md`, increasing cron frequency or
  concurrency is an approval gate. This is a deliberate switch: the shipping
  default is scheduler-off, and autonomous outreach remains prohibited regardless;
- fact-promotion strictness: the reviewed `fact_promotion_policy` database row
  (owner lane) sets whether autonomous claim promotion runs at all
  (`auto_promote`), how many independent sources corroborate a claim
  (`min_independent_sources`, default 2), which source kinds may promote alone
  (`single_source_kinds`, default `regulatory_filing` only), and which trust
  levels never corroborate (`excluded_trust_levels`, default `untrusted_upload`
  **and** `unknown` — `unknown` is also the `sources.trust_level` column
  default, so a source recorded without an explicit trust level never
  corroborates). `official_source_domains` (empty by default) is **not** read by the
  promotion predicate: it is consulted in exactly one place, where it decides
  whether a source the model labelled `regulatory_filing` keeps that kind or
  degrades to `public_web`. With the shipped defaults that is what keeps
  single-source promotion unreachable — no host is allowlisted, so nothing ever
  holds the only kind that may promote alone. **If you widen
  `single_source_kinds`, be aware that no host allowlist constrains the added
  kinds**: adding `company_website` means one model-labelled URL can promote a
  claim on its own. Widen it only together with `auto_promote=false`, or accept
  that the added kind is trusted on the model's label. With `auto_promote`
  disabled, nothing is promoted autonomously and every claim reaches the human
  `evaluate-lead` gate;
- sector metric ontologies and market-model types;
- source budgets, review capacity, and escalation service levels;
- backup/restore objectives, resource limits, and stable volume names;
- regional language, procurement, regulatory, and data-localization policy.

Each change needs an owner, reason, effective date, test delta, rollback
condition, and update to the customization profile’s change record.

## `DO_NOT_CUSTOMIZE_DIRECTLY` generated or frozen files

| Files | Correct change path |
|---|---|
| Existing numbered migrations | Never edit an applied migration. Add a new immutable forward migration, checksum it, and test apply/reapply/rollback strategy. Then **regenerate `docs/SCHEMA.sql`** (`python3 -B scripts/generate_schema_reference.py`, needs PostgreSQL 17 `initdb`, `pg_ctl`, `psql` and `pg_dump` on `PATH` — the server package, not `postgresql-client-17` alone) and regenerate the manifest. The schema reference is not optional bookkeeping: `tests/v3/test_erasure_gap_enumeration.py` enumerates its tables to prove the erasure-gap list in `data_retention.md` is complete, so a new table that is only in `migrations/` is invisible to that net and the default offline gate still reports `PASS`. Give every new table a disposition in that test, name it in `data_retention.md` if it can hold subject data, and prove currency with `python3 -B scripts/verify_offline.py --with-schema-reference`. |
| `config/runtime/openclaw.json` | Generated by the channel renderer. Change reviewed source config/overlay/environment input and render again. |
| `manifest.json` | Generated by `scripts/build_release_manifest.py` after all tests; never hand-edit a hash or inventory. |
| `runtime-packages/**`, image/package locks, `deployment-lock.json` | Pin exact versions, then regenerate the lock with the two-pass procedure (`npm install --package-lock-only --omit=dev --allow-remote=all`, then `npm install --omit=dev --omit=peer --ignore-scripts --no-audit --no-fund`, then `rm -rf node_modules` — pass 2 reifies ~27,000 files that fail `--pristine`) — a single pass yields a lock `npm ci` rejects. Rebuild the image and repeat the supply-chain and G6 gates. |
| Canonical specialist schemas | `workspaces/schemas/` is mirrored byte-for-byte at `workspaces/vc-chief/vc/schemas/`. There is no generator: edit **both** copies. The contracts suite fails on any drift. |
| `.env`, raw approval tokens, provider credentials | Supply through the reviewed secret/runtime path. Never commit, copy into reports, or encode in the customization profile. |
| `config/exec-approvals.json` | The reviewed agent exec allowlist. `tests/infrastructure` pins its exact two entries, `validate_skill_system.py` cross-checks every agent-reachable helper against it, and the Compose initializer pins its reviewed keys — so an edit fails the offline gate. Changing the allowlist means changing the agent contract, the launcher inventory under `workspaces/vc-chief/vc/bin/agent/`, that test, and the initializer assertion together, then rebuilding. On the `2026.8.1` base the runtime store is the `exec_approvals_config` row of the state database, not a file: the initializer loads the read-only image-baked seed at `/opt/openclaw-seed/exec-approvals.json` into that row, deletes any `exec-approvals.json` — and any `.doctor-importing` claim file — left in the state directory, and asserts that neither is there afterwards, because a leftover file makes every approvals read and write throw. The harness's socket token lives in that row too, so the old reason for leaving a writable JSON copy in the state volume no longer exists. |
| Postgres/OpenClaw/Lobster live state and named-volume contents | Use typed operations, backup/restore, migrations, and lifecycle locks. Never edit state files by hand. |
| Canonical schemas in isolation | Change the agent contract, skill, schema, fixtures, resolver, config, helper/workflow consumer, and version together. |

## Do not weaken

These are security and evidence invariants, not fund preferences:

- only the chief is channel-facing and only the chief delegates;
- specialists cannot delegate, write, approve, contact, spend, or mutate;
- the steward executes only exact immutable typed launchers;
- Postgres, not Markdown memory or an agent assertion, owns business state;
- stable signed provider/account/sender identity owns each preference and
  attachment capability; user text and copied tokens never do;
- only PDF, PPTX, XLSX, and CSV enter the governed document lane; unsupported
  media is blocked before model input;
- identity resolution is exact-first, fuzzy matches are review-only, and create
  must consume a valid resolver decision;
- untrusted input never changes policy or becomes instruction;
- submitted claims do not become verified facts without provenance;
- material conclusions have evidence IDs and temporal status;
- approvals are scoped, expiring, hash-bound, authenticated, single-use, and
  atomic with the governed action;
- idempotency, expected revision, audit logs, and fail-closed errors remain;
- raw secrets and unnecessary personal data are never placed in prompts,
  reports, operational memory, or logs.
- controlled evolution cannot change the running deployment, permissions,
  model/search provider, schema, or business state; only `skillify` may write a
  size-limited scanned **pending** Workshop artifact;
- only `vc-chief` receives `skill_workshop`; the trusted runtime hook must keep
  every action outside `create`/`update`/`revise`/`list`/`inspect` blocked, and
  every non-chief caller with it. On the `2026.8.1` base that is ten of fifteen
  actions: `apply`, `reject`, `quarantine`, `restore_collection`, `complete`,
  `read`, `prepare_patch`, `patch`, `evaluate`, `history`. The last five are
  authoring and inspection actions this release deliberately leaves
  unreachable; widening the allowlist to admit any of them is a behaviour
  change needing its own review, not a customization; and
- OpenClaw's autonomous Skill Workshop capture
  (`skills.workshop.autonomous.mode`, pinned `"off"`; the `2026.7.1` spelling
  `skills.workshop.autonomous.enabled` is retired and startup-fatal if it is
  re-added) remains off. With it off, a durable
  instruction the harness detects in a session is only offered back to the user
  on a later turn; turning it on lets a session create a pending Workshop
  proposal on its own, with no user decision in between. That is a separate
  privacy/security design and commissioning decision, not ordinary tuning. Note
  that the detection itself runs either way — the flag governs what happens to
  the result, not whether sessions are examined. `2026.8.1` renames the key to
  `skills.workshop.autonomous.mode` with the enum `off|propose|auto` and a new
  default of `auto`, so this release pins `"mode": "off"` explicitly — deleting
  the key rather than replacing it would silently opt in to applying captured
  proposals. The Control UI's Workshop surface was re-reviewed for that image
  before the base moved: it adds a manual scan action that runs independently of
  this flag, which is one more reason the two controls that actually bind here
  are the `vc-chief`-only tool allowlist and the image-owned trusted-context
  hook rather than the flag. Re-run that review against any newer image.

If a deployment needs to weaken one of these invariants, it is a different
threat model and must be redesigned and independently reviewed—not marked as a
routine customization.

## Generated and coupled files

Do not edit a policy in isolation. At minimum keep these coupled:

- rubric Markdown, rubric JSON **content**, and the scoring fixtures. The
  policy version itself is **frozen at `3.0` for this release — do not bump
  it**: customizing weights, bands, and gates neither requires nor permits a
  version change. The value is re-asserted in the helper's `_load_rubric`
  guard (`workspaces/vc-chief/vc/bin/vcops.py`, any other value fails closed as
  `rubric_invalid`, exit 3, on every scoring call), in four `--policy-version`
  argparse defaults in the same file, in the two `--policy-version` literals in
  `workspaces/vc-chief/vc/workflows/evaluate-lead.lobster`, in the helper
  `POLICY_VERSION`, and in applied migration
  `008_workflow_version_binding.sql`, which cannot be edited after bootstrap
  without a new forward migration. Every one of those pins now fails closed
  before release. G4 executes the workflows end-to-end against this tree:
  `evaluate-lead.lobster` catches a drifted rubric JSON `"version"` as
  `rubric_invalid` and a drifted `--policy-version` on its `evaluation_save`
  step as `rubric_version_mismatch`, while a drifted helper `POLICY_VERSION`
  is caught in the **document** lane instead — `inbound-intake` and
  `document-ingest` write `document_extractions` with a bound
  `workflow_request_id`, whose `document_extractions_workflow_versions`
  trigger (migration 008) is the only place that literal is enforced;
  `evaluate-lead` never writes that table, and `document-lead-intake` only
  reads an existing extraction. The offline suite covers the rest: a `tests/v3` pin binds the rubric
  JSON version, the helper guard and its four argparse defaults, both
  `evaluate-lead.lobster` literals, the migration literal, and the prose
  `Policy version:` line in `scoring-rubric.md` to one another, so no member
  of the set can drift alone;
- resolver policy, migration schema, typed CLI, all four lead-creating
  workflows (`inbound-intake`, `inbound-text-intake`, `document-lead-intake`,
  `outbound-scout`), schemas, and retrieval fixtures;
- agent contract, shared skill, canonical output schema, resolver route, config
  skill/tool allowlist, and semantic fixtures;
- pending Workshop skill, owner, router/config entry, affected `AGENTS.md` and
  `TOOLS.md`, canonical schemas, positive/negative/adversarial fixtures,
  `scripts/validate_skill_system.py`, public audit, image, and release manifest;
- model/search selection, renderer, environment validator, provider packages,
  frozen research fixtures, and exact-image evidence;
- channel selection, rendered overlay, stable multi-user allowlist, trusted
  context plugin, document/preference workflows, approval policy, environment
  validator, and live acceptance evidence;
- file inventory, release manifest, and offline evidence after any packaged
  change.

Customization is complete only when the coupled artifacts agree and the new
fixtures pass. The validator rejects missing/mismatched hashes for the twenty
reviewed artifacts, so an edit to any of them after review fails closed at
the next bootstrap, update, restore or rotate run. The remaining customizable policy files
are pinned only in `manifest.json`, which no lifecycle script re-checks —
`verify_release.py --pristine` and the offline manifest-currency gate are
their only backstop, so re-run those after any post-review policy edit. A
`reviewed` JSON flag without that evidence is a false claim.
