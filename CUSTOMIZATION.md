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
4. Re-pin both inventories, because the files you just edited are hash-pinned
   in two places:

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
`check_customization.py`, which every lifecycle script runs before it mutates
anything. So editing the profile changes what the validators will accept, never
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
| Scoring criteria, weights, missingness, thresholds | `workspaces/vc-chief/vc/scoring-rubric.md` and its machine JSON, `tests/g3`, scoring evals | The shipped weights, bands and gates are examples; the software does not assess their predictive quality. Evidence quality and coverage are separate inputs, and unknown is never scored as negative. Update helper/workflow policy versions together. **The recommendation band boundaries are re-encoded in a database CHECK, so changing them means changing the database too, and how you do that depends on whether you have bootstrapped yet.** Before your first `bootstrap.sh`, edit the CHECK in `migrations/007_scoring_readiness_gate.sql` directly — no migration ledger exists yet, so nothing is bound to its checksum. (`manifest.json` does record it, so re-pin the manifest afterwards as step 4 requires, or `verify_release.py --pristine` reports your own edit as an integrity mismatch.) **After bootstrap, never edit 007** (or any applied migration): `migrate.sh` compares each file against the recorded checksum and fails closed on every later `bootstrap`, `update` and `rotate_runtime_role` run. Add a new numbered forward migration instead that drops and recreates the CHECK with your bands, then regenerate `docs/SCHEMA.sql` and the manifest. Until the rubric and the CHECK agree, `evaluate-lead` fails at persistence and the G4 gate fails. `workspaces/vc-chief/vc/governance_lint.md` also refers to the band edges, so review it against your bands. The rubric is image-baked, so re-run `./scripts/bootstrap.sh` on a deployed system. |
| Sources and outbound discovery | `primary_sources.md`, `active_sourcing.md`, `passive_sourcing.md`, `inbound_sources.md`, `third_party_connectors.md`, `workspaces/outbound-scout/USER.md` | Record stable URL/provider, purpose, allowed data, cost/rate/terms, expected signal, owner, and stop rule. Which sources you admit, and on what terms, is your decision; check the provider's terms of use with your counsel if in doubt. |
| Research depth, cost, and models | `research_depth.md` **and the mirroring numbers in `workspaces/shared-skills/research-depth-control/SKILL.md` (retune both together)**, `.env` (`VC_MODEL_PROVIDER`, `VC_PRIMARY_MODEL`, `VC_FAST_MODEL`, common model limits), profile | Select OpenAI, native Ollama, or one reviewed HTTPS custom provider. Benchmark tool calling, JSON, context, prompt injection, quality, privacy, latency, and cost on frozen suites. For Ollama, validate the private endpoint, pulled models, host capacity, and restart behavior. Equal model IDs are allowed only when deliberately reviewed. The shipped tier split (PRIMARY: `vc-chief`, `market-mapper`, `memo-writer`; FAST: the other nine, including the scoring gate and the sole DB writer) is a cost-first sample, not a benchmarked optimum. `.env` defines the two model IDs; which agent uses which is the `"model"` field on each agent in `config/openclaw.json` (a hash-pinned reviewed artifact — re-pin both inventories after editing it). |
| Search and fetch provider | `.env` (`VC_WEB_SEARCH_PROVIDER`, `VC_WEB_FETCH_PROVIDER` and selected key), `primary_sources.md`, `third_party_connectors.md`, profile | Keep the generic agent tool contract. Choose `auto` only with direct OpenAI, or explicitly select a native provider: `duckduckgo` (keyless; the only search provider bundled in the base image), `firecrawl`/`tavily` (keyed; present because `runtime-packages/package.json` pins their plugin packages — keep those pins), or `brave`/`perplexity`/`exa`/`searxng`/`parallel-free` (not pinned — pin the plugin package + rebuild, or render fails closed). Selecting `firecrawl` for search also makes it the fallback the fetch lane uses when local extraction returns nothing, unless you pin a fetch provider; see the search table in `README.md`. Review coverage, ranking, processor terms, retention, rate/cost, egress, failure behavior, and source quality. A provider switch requires research regressions and exact-image/config validation. |
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
  regenerate the lock with `npm install --package-lock-only` in
  `runtime-packages/`, rebuild the image, and re-run the G6 gate; that
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
  re-pin **both** inventories as step 4 requires — record the new artifact hash
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
  the chosen schedule. Per `approval-policy.md`, increasing cron frequency or
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
| Existing numbered migrations | Never edit an applied migration. Add a new immutable forward migration, checksum it, test apply/reapply/rollback strategy, and regenerate the manifest. |
| `config/runtime/openclaw.json` | Generated by the channel renderer. Change reviewed source config/overlay/environment input and render again. |
| `manifest.json` | Generated by `scripts/build_release_manifest.py` after all tests; never hand-edit a hash or inventory. |
| `runtime-packages/**`, image/package locks, `deployment-lock.json` | Pin exact versions, regenerate the lock with `npm install --package-lock-only`, rebuild the image, and repeat the supply-chain and G6 gates. |
| Canonical specialist schemas | `workspaces/schemas/` is mirrored byte-for-byte at `workspaces/vc-chief/vc/schemas/`. There is no generator: edit **both** copies. The contracts suite fails on any drift. |
| `.env`, raw approval tokens, provider credentials | Supply through the reviewed secret/runtime path. Never commit, copy into reports, or encode in the customization profile. |
| `config/exec-approvals.json` | The reviewed agent exec allowlist. `tests/infrastructure` pins its exact two entries, `validate_skill_system.py` cross-checks every agent-reachable helper against it, and the Compose initializer pins its reviewed keys — so an edit fails the offline gate. Changing the allowlist means changing the agent contract, the launcher inventory under `workspaces/vc-chief/vc/bin/agent/`, that test, and the initializer assertion together, then rebuilding. The state-volume copy is left writable for OpenClaw's socket token and is never re-seeded once present. |
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
  `apply`, `reject`, `quarantine`, unknown actions, and non-chief callers
  blocked; and
- OpenClaw's autonomous Skill Workshop capture
  (`skills.workshop.autonomous.enabled`) remains off. With it off, a durable
  instruction the harness detects in a session is only offered back to the user
  on a later turn; turning it on lets a session create a pending Workshop
  proposal on its own, with no user decision in between. That is a separate
  privacy/security design and commissioning decision, not ordinary tuning. Note
  that the detection itself runs either way — the flag governs what happens to
  the result, not whether sessions are examined. OpenClaw releases after the
  pinned image also add a manual Control UI action that scans recent sessions
  independently of this flag, so moving to a newer image means re-reviewing the
  Workshop surface of the Control UI before deploying.

If a deployment needs to weaken one of these invariants, it is a different
threat model and must be redesigned and independently reviewed—not marked as a
routine customization.

## Generated and coupled files

Do not edit a policy in isolation. At minimum keep these coupled:

- rubric Markdown, rubric JSON (`scoring-rubric.v3.json`'s `"version"`), the
  helper `POLICY_VERSION`, the two `--policy-version` literals in
  `workspaces/vc-chief/vc/workflows/evaluate-lead.lobster`, and the scoring
  fixtures. No offline gate catches drift here: a mismatch first appears in
  production as `rubric_version_mismatch` when a lead is evaluated;
- resolver policy, migration schema, typed CLI, both intake workflows, schemas,
  and retrieval fixtures;
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
fixtures pass. The validator rejects missing/mismatched reviewed-artifact
hashes, so a policy edit after review fails closed. A `reviewed` JSON flag
without that evidence is a false claim.
