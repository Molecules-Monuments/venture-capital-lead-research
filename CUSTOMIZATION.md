# Version 3.0 customization guide

This package is a publishable reference system, not a universal investment
policy. It ships inert and must fail closed until an accountable operator has
replaced the sample fund profile, reviewed the security/privacy controls, and
passed the relevant evals.

## Required publication workflow

1. Copy `config/customization-profile.example.json` to
   `config/customization-profile.json`.
2. Replace every placeholder, set only reviewed booleans to `true`, record the
   stable reviewer/change record, populate `review.reviewed_artifacts` with the
   current SHA-256 of every coupled policy/eval file, and set `status` to
   `reviewed` last.
3. Apply the corresponding edits in the files below. The JSON profile records
   the decision; it does not silently rewrite policy.
4. Run `python3 scripts/check_customization.py
   config/customization-profile.json .env`. This binds the reviewed timezone,
   model/provider IDs, search/fetch selection, channel selection, allowed-user
   lists, attachment limit, and destination IDs to the exact deployment
   environment; validating the profile alone is not a publication gate.
5. Rebuild the routing, scoring, retrieval, specialist, memo, privacy, and live
   channel fixtures affected by the changes. Passing old fixtures against a new
   thesis is not evidence.
6. Run all offline gates and the applicable live acceptance matrix before
   selecting a channel or production traffic.

## `MUST_CUSTOMIZE` files

| Decision | Files | How to customize and re-evaluate |
|---|---|---|
| Organization, operator intent, timezone | `workspaces/vc-chief/USER.md`, `.env` (`TZ`), customization profile | State the product objective, fund strategy, reporting style, stable deployment owner, and authority limits. Re-run orchestration and channel tests. |
| Thesis, stage, sector, geography, check/ownership targets | `workspaces/vc-chief/vc/thesis.md`, `exclusion_criteria.md`, `prequalification.md`, profile | Use fund-specific policy; distinguish hard mandate from preferences. Add chronological labeled cases including unconventional winners and confident false positives. |
| Scoring criteria, weights, missingness, thresholds | `workspaces/vc-chief/vc/scoring-rubric.md` and its machine JSON, `tests/g3`, scoring evals | Keep evidence quality separate from coverage and unknown separate from negative. Backtest on locally labeled, time-split cases; never import famous-investor weights. Update helper/workflow policy versions together. **Changing the recommendation band boundaries also requires a reviewed edit to the database CHECK in `migrations/007_scoring_readiness_gate.sql` (it re-encodes the same band names and numbers); until both agree, `evaluate-lead` fails at persistence and the G4 gate fails.** |
| Sources and outbound discovery | `primary_sources.md`, `active_sourcing.md`, `passive_sourcing.md`, `inbound_sources.md`, `third_party_connectors.md` | Record stable URL/provider, purpose, allowed data, cost/rate/terms, expected signal, owner, and stop rule. Measure marginal accepted leads and false-positive burden before automatic promotion. |
| Research depth, cost, and models | `research_depth.md` **and the mirroring numbers in `workspaces/shared-skills/research-depth-control/SKILL.md` (retune both together)**, `.env` (`VC_MODEL_PROVIDER`, `VC_PRIMARY_MODEL`, `VC_FAST_MODEL`, common model limits), profile | Select OpenAI, native Ollama, or one reviewed HTTPS custom provider. Benchmark tool calling, JSON, context, prompt injection, quality, privacy, latency, and cost on frozen suites. For Ollama, validate the private endpoint, pulled models, host capacity, and restart behavior. Equal model IDs are allowed only when deliberately reviewed. The shipped sample tier split (PRIMARY: `vc-chief`, `market-mapper`, `memo-writer`; FAST: the other nine, including the scoring gate and the sole DB writer) is a cost-first starting point, not a benchmarked optimum — revisit it for your fund and consider PRIMARY for `qualification-analyst` and `data-steward` if budget allows. |
| Search and fetch provider | `.env` (`VC_WEB_SEARCH_PROVIDER`, `VC_WEB_FETCH_PROVIDER` and selected key), `primary_sources.md`, `third_party_connectors.md`, profile | Keep the generic agent tool contract. Choose `auto` only with direct OpenAI, or explicitly select a native provider: `duckduckgo` (keyless, bundled), `firecrawl`/`tavily` (bundled, keyed), or `brave`/`perplexity`/`exa`/`searxng`/`parallel-free` (non-bundled — pin the plugin package + rebuild, or render fails closed). Review coverage, ranking, processor terms, retention, rate/cost, egress, failure behavior, and source quality. A provider switch requires research regressions and exact-image/config validation. |
| Approvers and governed actions | `approval-policy.md`, channel overlays/IDs in `.env`, profile | Use stable authenticated IDs, separation of duties, target/action limits, expiry, and atomic consumption. Test reject, expiry, mismatch, replay, and rollback. Never replace IDs with display names. |
| Privacy, lawful basis, confidentiality, retention | `trust_boundaries.md`, `storage_tiers.md`, `data_retention.md`, `document_intake.md`, profile | Obtain jurisdiction-specific review. State purpose/lawful basis, allowed fields, audience, processors, retention, deletion, legal hold, and restore behavior. Do not mark reviewed until purge/isolation tests pass. |
| Channels, users, attachments, notification policy | `.env`, channel overlay, `channel_policy.md`, `document_intake.md`, `notification_policy.md`, `docs/CHANNELS.md`, profile | Begin with `PRIMARY_CHANNEL=none`; use one provider, exact destination IDs, and a reviewed comma-separated stable-user list. Set a measured 1–50 MiB transport cap. Test per-peer sessions, principal preference isolation, signed path scope, all four supported documents, hostile/unsupported media, provider replay, and restart. Teams Graph/SharePoint channel files are a separate privileged design. This release does not authorize proactive outreach. |
| User preference memory | `AGENTS.md`, `trust_boundaries.md`, `data_retention.md`, preference workflows/helper/migration/tests, profile | Keep the five-key closed schema unless undertaking a versioned schema migration. Define retention/deletion response, explain explicit versus three-event inference, test user isolation/group denial/forget cutoff/replay, and never use preferences as evidence, permission, or scoring input. |
| Agent roster/routes/skills | `config/openclaw.json`, `workspaces/vc-chief/vc/RESOLVER.md`, affected agent `AGENTS.md`, shared `SKILL.md`, canonical schemas | Preserve one channel-facing chief, no specialist delegation, bounded steward exec, and no external writes. `skillify` may create a complete pending Workshop candidate; only an operator repository release may activate it. Update schemas, dependency fixtures, allowlists, documentation, manifest, and release inventory together. A new persona without distinct information is not a useful agent. |
| Memo and reporting | `memo-writing/SKILL.md`, memo schema/template/evals, operator intent | Preserve claim-evidence mapping, case/countercase, cruxes, falsifiers, next diligence, snapshot hash, and recommendation parity. Customize length and audience only after grounding tests. |

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
  image rebuild) and is confirmed by the exact-image (G6) gate. Selecting a
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
  record the new artifact hash in `config/customization-profile.json`
  (`review.reviewed_artifacts` plus the change record — the file is a
  hash-pinned reviewed artifact), re-run `./scripts/bootstrap.sh` so the change
  reaches the gateway's rendered runtime config (the gateway never reads the
  host file directly), and then seed the schedule with
  `./scripts/schedule_jobs.sh` (idempotent; tunable
  via `VC_SCAN_CRON`/`VC_SCAN_TZ`/`VC_SCAN_DELIVERY`, optional `VC_HEARTBEAT_CRON`).
  It uses OpenClaw's native cron to send `vc-chief` a fixed scan instruction on
  the chosen schedule. Per `approval-policy.md`, increasing cron frequency or
  concurrency is an approval gate. This is a deliberate switch: the shipping
  default is scheduler-off, and autonomous outreach remains prohibited regardless;
- fact-promotion strictness: the reviewed `fact_promotion_policy` database row
  (owner lane) sets whether autonomous claim promotion runs at all
  (`auto_promote`), how many independent sources corroborate a claim
  (`min_independent_sources`, default 2), which source kinds may promote alone
  (`single_source_kinds`, honored only for hosts on the reviewed
  `official_source_domains` allowlist — empty by default), and which trust
  levels never corroborate (`excluded_trust_levels`, default untrusted
  uploads). A cautious fund disables `auto_promote` and reviews claims at the
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
| `runtime-packages/**`, image/package locks, `deployment-lock.json` | Use the audited dependency/update process and repeat supply-chain and compatibility gates. |
| `.env`, raw approval tokens, provider credentials | Supply through the reviewed secret/runtime path. Never commit, copy into reports, or encode in the customization profile. |
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
- OpenClaw autonomous Self-learning remains disabled. Enabling its additional
  transcript-review model pass is a separate privacy/security design and
  commissioning decision, not ordinary tuning.

If a deployment needs to weaken one of these invariants, it is a different
threat model and must be redesigned and independently reviewed—not marked as a
routine customization.

## Generated and coupled files

Do not edit a policy in isolation. At minimum keep these coupled:

- rubric Markdown, rubric JSON, helper policy version, workflow arguments, and
  scoring fixtures;
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
