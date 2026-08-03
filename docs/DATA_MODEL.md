# Data Model and Persistence Contract

System version: `3.0.0`  
PostgreSQL target: `17`  
Schema migrations: immutable ordered series; discover and apply every numbered
file through the manifest's current highest migration. Never infer the current
schema from this prose line.  
Full DDL reference: [`SCHEMA.sql`](SCHEMA.sql) is a generated, read-only
schema-only snapshot of the database after all migrations are applied — a
single-file view of every table, function, trigger, constraint, and runtime
grant. It is documentation, not a migration (nothing applies it); the
`migrations/` directory remains the authoritative source.  
Runtime grants begin in `migrations/002_runtime_grants.sql`; later migrations
grant only their reviewed additions.

## Authority boundary

Postgres is authoritative for the VC domain: workflow request claims,
companies, leads, evidence provenance, facts, compiled truth, contradictions,
trajectories, evaluations, memos, approval records, notification delivery
records, and business-workflow audit.

Postgres is not the Task Flow database. OpenClaw owns sessions and Task Flow state in its state volume, including flow revisions and the exact Task Flow lifecycle. Lobster owns its deterministic step and resume envelopes. `workflow_runs` is a business audit/reconciliation record: it links a Task Flow/Lobster run to committed domain work but never replaces OpenClaw's flow state. A successful Task Flow is not evidence of a committed business transaction, and a successful Postgres run does not authorize changing Task Flow directly.

Workspace memory is operational convenience only. It may point to Postgres IDs but cannot override a fact or approval record.

## Installation and migration integrity

`openclaw_owner` owns schema objects. `openclaw_runtime` is created by `000_roles.sh` and receives only the grants in `002_runtime_grants.sql`.

Migration files are immutable after release. The installer computes each file's lowercase SHA-256 outside Postgres, applies it in a transaction, and then calls:

```sql
SELECT register_schema_migration('001', '001_initial_v2', '<64-character-file-sha256>');
```

The registered name is the full migration file stem, version prefix included, matching `scripts/migrate.sh` (`name="${migration_file%.sql}"`).

`schema_migrations` stores the supplied checksum, is append-only, and rejects a repeated version whose name or checksum differs. The registration function intentionally does not claim it can hash the client-side SQL file. The install/update script or release manifest must supply and verify the real file digest. Missing registration, a checksum mismatch, an unexpected migration, or a migration row without a matching release-manifest entry is a hard deployment failure.

The initial migration uses `CREATE ... IF NOT EXISTS` for controlled repeat application. That supports idempotency tests; it is not a license to edit the migration or repair drift by re-running it. Drift is reported and repaired through a new reviewed migration.

## Identity, provenance, and evidence

### Companies and leads

- `companies` is the canonical company record. `canonical_domain`, when known, is normalized lowercase and unique.
- `leads` is an intake/opportunity record and may point at one company. Its required `idempotency_key` prevents repeated intake writes.
- Provider events are deduplicated by provider, account, and stable event ID. This is separate from the application idempotency key.
- `row_version` on companies and leads supports optimistic updates. The trigger increments it on every update.
- Unknown origin and evidence states remain explicit. They are never rewritten to verified values merely to satisfy a required field.
- `workflow_requests` claims the canonical complete inbound/outbound outer
  payload before any company, lead, workflow-run, or extraction mutation.
  `(workflow_id, idempotency_key)` is unique and append-only. A replay with any
  different canonical argument—or a different inspected document SHA for
  inbound—fails before the business mutation lane.

### Sources and artifacts

- `sources` describes the origin of evidence: URI, stable provider identity, publisher/time, trust boundary, confidentiality, and optional content hash.
- `evidence_artifacts` describes content identity and storage. Its lowercase SHA-256 is globally unique.
- An artifact never contains `lead_id`. The same immutable content may be evidence for many leads.
- `lead_artifacts` is the per-lead provenance join. It records the source, association role, filename/locator, submitter, receive time, and provenance metadata. `(lead_id, artifact_id)` is unique, eliminating the historical bug where a global document hash attached content to the first lead only.
- Foreign keys use `RESTRICT` for evidence history. Runtime deletion is not granted.

### Document extraction

`document_extractions` records a bounded parser run over an artifact. The
artifact/extractor/version/idempotency tuple protects operator retries. Fixed
inbound runs additionally carry a globally unique `workflow_request_id`; a
database trigger requires its key, workflow run, and artifact SHA to match the
pre-mutation claim. Thus one logical request cannot create a second extraction
through a new artifact ID. It records the detected type, output content hash
and location, resource counts, formula flag, safety findings, terminal status,
and structured error. A successful extraction requires an output URI and
extracted-text hash.

`document_facts` links a normalized fact to the extraction and preserves a page, sheet/cell, paragraph, or structured locator. It does not duplicate the fact value.

The database does not make an unsafe file safe. Canonical-root, regular-file, symlink, signature/MIME, size, macro, archive-expansion, page/sheet/row/cell, formula, and output-path checks happen before these rows are written.

## Typed facts and citations

`facts` is append-oriented. A record includes:

- company and optional lead/run identity;
- fact type plus an explicit normalized definition and definition version;
- exactly one typed value (`text`, `numeric`, `boolean`, `date`, `json`) or explicit `unknown`;
- the original representation;
- unit, ISO currency, period, cohort, and measurement basis where applicable;
- evidence status, numeric confidence, observed/source/valid time;
- a superseded fact link, version, creator, and metadata.

Typed-value checks prevent contradictory storage such as a row being both text and numeric. Currency codes are three uppercase letters. Period and validity ends cannot precede their starts. Superseding appends a new fact and links the prior fact; it does not erase history.

`fact_sources` gives every cited assertion a stable source and optional artifact/extraction locator. Evidence roles are primary, supporting, contradicting, or context. Material persisted assertions should be written with at least one `fact_sources` row in the same transaction.

Statuses remain distinct:

- `submitted_claim`: reported but not independently established;
- `verified_fact`: evidence and provenance meet the current verification policy;
- `derived_inference`: an explicit, reproducible inference;
- `contradicted`, `stale`, or `retracted`: retained historical states;
- `unknown`: absence is preserved.

On the autonomous path, the `evidence-record` workflow writes claims with a
deterministic `claim_hash` content identity so independent sources attach to
one claim row instead of duplicating it. Promotion from `submitted_claim` to
`verified_fact` happens only in `promote_submitted_claim`, a SECURITY DEFINER
function that evaluates the corroboration predicate in SQL against the
reviewed `fact_promotion_policy` row (minimum count of independent-provenance
sources, single-source kinds gated by the reviewed official-domain allowlist,
and trust levels excluded from corroboration — untrusted uploads never
corroborate). Source independence for web/URI sources is keyed by **verified
content identity** (`sources.content_sha256`, the hash of the fetched page
bytes the steward records), not by host: a bare model-supplied URL with no
content hash contributes no independent key, and two URLs that returned
identical content collapse to one — so recording the same claim twice from two
invented hosts no longer corroborates. Non-URI sources are keyed by provider
identity (document artifacts are already content-addressed as
`artifact:<sha>`), and any unclassifiable source collapses into one shared key
so it can never multiply independence. The remaining residual — content is
still model-supplied, so a boundary that fetches the URL itself is the full
tamper-proof closure (the deferred CR-001 part-6 work) — is backstopped by the
human evaluate-lead approval gate on the compiled-truth snapshot. Document-lane
sources bound to
specific leads may only corroborate those leads: `evidence-record` refuses an
extraction whose artifact carries `lead_artifacts` rows for other leads but
none for the target lead, so an operator-trusted document for company A cannot
lend its trust boundary to claims about company B (artifacts from the
lead-free manual ingest lane remain citable). Promotion supersedes the claim with a new `verified_fact` row and
copies its provenance links; facts stay append-only. The policy row is the
promotion-strictness knob: owner-lane only, `SELECT`-only for the runtime role,
and `auto_promote = FALSE` turns the autonomous promotion off entirely so
claims surface unpromoted at the human evaluation gate.

## Compiled truth

`compiled_truth` is a versioned, cited snapshot for one lead and company. It
holds current view, coverage, the full frozen fact/source history,
contradiction and trajectory histories, database-derived decision guards,
timeline, missing data, delta from an optional prior snapshot, policy version,
evidence-packet hash, compiler, and freshness time. Only one snapshot per lead
may be `current`. The evidence hash covers all of those ledgers, not just the
surviving current facts. Active blocking contradictions and identity conflicts
therefore remain visible even when their facts are ineligible for current
scoring.

`compiled_truth_facts` is the snapshot's fact ledger. A database trigger enforces that a `current` support fact:

1. has `verified_fact` status; and
2. has at least one row in `fact_sources`.

Historical, contradicted, stale, and missing-context rows remain available but cannot masquerade as current verified coverage. Snapshot generation and fact-link insertion belong in one transaction. A stale, draft, invalid, or incomplete snapshot cannot support a final evaluation or memo at the application gate.

## Contradictions and trajectories

`contradictions` represents both actual incompatibility and the explicitly different outcomes `ordinary_change`, `superseded`, `stale`, `not_comparable`, and `identity_conflict`. It stores normalized definition, unit/currency, cohort/basis, overlap, explanation, severity, and review/resolution state. `contradiction_facts` preserves every participating fact.

An actual contradiction requires incompatible assertions about the same entity and normalized definition whose validity periods overlap. Different currencies, units, periods, cohorts, or bases are `not_comparable` until a cited normalization exists. Two non-overlapping dated observations are an ordinary change, not a contradiction.

`trajectory_events` stores a typed direction (`up`, `down`, `flat`, `volatile`, `unknown_baseline`, or `not_comparable`) over the ordered facts in `trajectory_points`. One point can only produce an unknown/not-comparable result. Score adjustment is database-bounded to `-5..+5`; a not-comparable result has zero adjustment. A cited dated FX normalization is required before comparing currencies.

## Evaluation and memo lineage

`evaluations` binds a score to one compiled-truth snapshot, evidence hash, rubric version, and workflow run. The fixed denominator is always 100; no weight redistribution is permitted. Scores are database-bounded and the score-to-band intervals are:

| Total score | Recommendation |
|---:|---|
| `[0, 50)` | `pass` |
| `[50, 66)` | `watch` |
| `[66, 82)` | `research_deeper` |
| `[82, 100]` | `high_priority` |

Two bands sit outside that mapping and are valid at **any** score, because they
record that the score is not decision-usable rather than what it was:
`insufficient_evidence` and `needs_human_review`. There are also two deliberate
overrides. A `[82, 100]` evaluation may be stored as `research_deeper` when
`scoring_details ->> 'override' = 'high_priority_prerequisites_missing'`. A
hard exclusion is stored as `pass` at **any** `total_score` in `[0, 100]` when
`scoring_details ->> 'override' = 'hard_exclusion'`: the criteria score is
preserved rather than zeroed (`scoring-rubric.md` documents `pass` as the
hard-exclusion outcome), so an integration must not assume a `pass` band
implies a sub-50 score. `evaluations_score_band_check` (migration `007`) is the
authority; an integration reading this table must handle all six band values,
not four.

`evaluation_criteria` stores each criterion's 0–5 score, fixed point weight, weighted points, evidence IDs, and rationale. A missing criterion is constrained to zero score and zero weighted points. Application validation must also prove criterion weights sum to 100 and stored weighted points sum to `total_score` before an evaluation becomes final.

For durable evaluation, `identity_reliable` and `blocking_contradiction` are
not caller assertions. The helper reads the same current compiled-truth row,
requires its decision-guard state to be complete, overwrites those two caller
fields with the frozen database values, and compares the frozen guard IDs to
live same-lead contradictions under the same advisory lock. Any difference
makes the snapshot stale and forces recompilation. The helper records caller
mismatches and persists the effective blockers. Criterion evidence must be a
`current` snapshot fact; adjustment evidence may reference another preserved
snapshot-ledger role.

`memos` binds versioned output to the exact compiled-truth and evaluation rows plus a frozen-evidence hash. It stores a content URI/hash and citation coverage. Approval status requires a stable reviewer and time. One approved memo per lead is allowed; a replacement first supersedes the old version transactionally.

## Workflow audit and cancellation

`workflow_runs` accepts Task Flow-compatible states plus local `started`:

```text
queued -> started|running -> waiting|blocked -> running -> succeeded|failed|cancelled|lost
```

`succeeded`, `failed`, `cancelled`, and `lost` are terminal. The transition trigger rejects movement out of a terminal state, making cancellation sticky. It also prevents flow-revision rollback, fills lifecycle timestamps, increments `record_version`, and records updates. A failed run requires an error class. The active-run index supports stale-run reconciliation.

There is exactly one governed edge out of a terminal state, added by migration 018: the recovery retry `failed -> queued`, reachable only through `retry_workflow_run(...)`. The trigger admits it only when the same statement also increments `attempt` and clears the previous attempt's `finished_at` and `error_class`, so an ordinary `transition_workflow_run(...)` call still cannot resurrect a terminal run. `succeeded`, `cancelled`, and `lost` have no edge out at all, and a run whose cancellation was requested is refused even if it later failed. Each retry appends a `workflow.retry` audit event carrying the prior attempt's status, error, and record version, so the attempt history survives the reset.

`attempt` counts recovery attempts (1 for a run never retried). `input_digest` is the SHA-256 of the fixed runner's canonical argument payload for the run. Together with `workflow_id`, `workflow_version`, `policy_version`, `idempotency_key`, and `input_hash`, it is immutable after insert (`guard_workflow_run_identity`), so a retry cannot reopen a run under different arguments: reusing a key with a changed payload fails closed as `idempotency_payload_mismatch` before any mutation. `input_hash` binds the run's lineage and metadata; `input_digest` binds the arguments themselves.

`orchestration_audit` is the durable delegation trail: one append-only row per `delegation_eval`, `return_assessment`, or `chief_output`, keyed to the lead (and workflow run), carrying the schema-valid packet plus the native Task Flow correlation handles (`flow_id`, `flow_revision`, `task_id`). It answers "which specialists were consulted for company X, what did each return, and why was it accepted or discarded" long after the model context is gone. Written only through the reviewed `orchestration-record` workflow; read back through the agent-lane `orchestration-show`.

`transition_workflow_run(...)` locks the row, checks the caller's expected record version, applies a valid transition, and appends a compact audit event. A revision conflict fails with SQLSTATE `40001`. Retry code must re-read state; it must not overwrite a cancellation or blindly increment a stale revision.

`request_workflow_cancel(...)` records the cancellation actor, reason, and request time while retaining the active status for cooperative shutdown. Once requested, the run may remain in its current state while it winds down, but it can terminate only as `cancelled`, `failed`, or `lost`; a late success or other forward transition is rejected. The later terminal transition still requires the new expected record version.

The `run_id` is stable application identity. `(workflow_id, idempotency_key)` is unique. `external_flow_id` and `flow_revision` are reconciliation references, not a second Task Flow authority.

## One-time approvals

`approvals` stores no raw token. It stores a lowercase SHA-256 token hash, canonical scope and scope hash, immutable action preview, exact action/target/payload, limits, actor/channel identity, mandatory expiration, and governed transaction identity.

Lifecycle is:

```text
pending -> approved -> consumed
        |           -> revoked|expired
        -> rejected|revoked|expired
```

Terminal decisions cannot reopen. The trigger prevents mutation of token, canonical scope, preview, action, target, and payload after creation. Approved/consumed states require the stable approver and approval channel; consumed requires a timestamp and governed transaction ID.

`decide_approval(...)` locks a pending request, rejects an expired or repeated decision, records the stable approver/channel, and appends an audit event. A new row inserted by `openclaw_runtime` is constrained to start pending and unissued. The trusted owner can restore a previously backed-up historical state; it does not represent an agent/runtime authority.

`consume_approval(...)` locks the hashed token row and validates approved state, issue/expiry window, exact scope hash, action, target, and payload before changing `approved` to `consumed`. It appends an audit event. It must be called in the same database transaction as the governed operation. If that operation rolls back, token consumption rolls back. A retry must present the same idempotency and governed-transaction identity; a replay after commit fails closed. The generic CLI therefore refuses standalone `approval-consume`; a future external integration must expose an action-specific helper that performs consumption and its governed mutation in one transaction.

`consume_approval_and_erase_lead(...)` additionally re-verifies the consumed approval's own stored scope against the erasure target inside the database: the scope must name exactly the lead being erased, and the approval's `lead_id` column, when set, must agree. An approval reviewed for one lead therefore cannot erase a different lead even for a direct SQL caller; the helper's client-side scope check is a convenience, not the authority.

## Governance proposals

`proposals` persists schema-change, source-policy, and skill-candidate proposals for operator review. The runtime role may insert and read them and may move `submitted` to `under_review`, but a guard trigger rejects any INSERT born decided and any direct UPDATE that enters a decided status: `accepted`/`rejected` transitions pass only through the audited SECURITY DEFINER `decide_proposal(...)` function, which locks the row, requires a stable reviewer identity, refuses re-decision, and appends an audit event. Decided proposals are immutable to the runtime role. The helper exposes this lane as the operator-gated `proposal-decide` command.

Stable allowlisted approver/channel identity is an application and configuration check in addition to these database constraints.

## Notification outbox

Creating a notification is not delivery. `notification_outbox` stores provider/account/destination stable IDs, related domain IDs, severity, policy/timezone, body hash and minimal payload, deliver time, idempotency/dedupe keys, attempt budget, claim lease, error class, provider message ID, and timestamps.

The provider claim/attempt lifecycle (`notification_attempts` and the
`claim_notification`/`finish_notification_attempt`/`release_held_notification`/
`cancel_notification` functions) is a **dormant** database contract with no
runtime caller. It is **superseded by native OpenClaw proactive delivery** —
cron `delivery.mode: "announce"` over the harness's durable outbound queue — so
this release does not ship a custom dispatcher and does not intend to. The
helper accepts only `internal_log`/`silent_log` and rejects claim/completion
calls; these functions must not be read as an enabled communication path.

Similarly `company_external_ids` is a declared, indexed identity surface that
this release's resolver reads but no shipped command populates; it is available
for an operator-loaded CRM/provider identity map, dormant until populated.

Lifecycle is:

```text
draft -> queued|held|logged|cancelled
queued|retry -> dispatching -> sent|retry|failed
held -> queued|cancelled
```

`silent_log` can only use the internal-log provider. Urgent messages require a governed urgent category. `(provider, account, dedupe_key)` prevents duplicate intents and provider message IDs prevent duplicate receipt attribution.

`claim_notification(worker, lease)` first marks expired in-flight attempts abandoned and returns their outbox rows to bounded retry (or terminal failure at the attempt limit). It then atomically selects one due row with `FOR UPDATE SKIP LOCKED`, increments its attempt count, creates a lease/claim, and inserts a `started` attempt. Provider I/O occurs outside that transaction.

`finish_notification_attempt(...)` validates the live claim and lease, records the provider result, and moves the outbox row to `sent`, bounded exponential-backoff `retry`, or `failed`. Success requires the stable provider message ID; failures require an error class. The unique claim and attempt number make repeated callbacks fail instead of recording a second result.

`release_held_notification(...)` releases only a held record whose `deliver_after` time has arrived. `claim_notification(...)` repeats the schedule check before dispatch. There is no ordinary early-release override for quiet hours. `cancel_notification(...)` cancels only a non-dispatching, nonterminal record. Both append an audit event. A new outbox row may begin only as draft, queued, held, or an internal logged notification and cannot arrive pre-populated with attempt or provider-delivery state.

Quiet hours and holiday calculation occur before queue eligibility. No approval token, raw secret, private document text, or unnecessary personal data belongs in a payload.

## Verified channel principals and bounded preferences

`channel_principals` assigns one internal ID to the exact
`(provider, account_id, sender_id)` tuple established by the signed channel
context. Conversation text and display names never select a principal.

`trusted_context_uses` consumes `(nonce, scope)` for one operation key and
provider event. An idempotent repeat may observe the same row; a different
principal, event, or operation fails as replay. Expired rows are audit/security
state and do not become user memory.

`preference_observations` is append-only and records only a closed
key/value/kind/event tuple. `user_preferences` contains the current bounded
value/status/evidence count. `preference_forget_markers` establishes a
per-principal/key cutoff so observations before a forget cannot be counted
again. `user_preference_audit` records activation and forgetting idempotently.

Preference writes/forgets require a direct-message capability. Explicit
supported values activate with one distinct event; inferred values require
three distinct events after the latest forget marker. Preference state cannot
act as evidence, permission, identity, scoring input, or approval.

## Entity resolution, aliases, and the source watchlist

Seven tables carry concepts described elsewhere in this document and in the
README but not previously named here. They complete the 42-table inventory:

| Table | Role |
|---|---|
| `company_aliases` | Alternate names for one company (trading names, former names, transliterations). Feeds trigram-indexed fuzzy matching. |
| `company_domains` | Registrable domains bound to one company. The primary exact-match key during resolution. |
| `entity_resolution_runs` | One resolution attempt: its input, threshold configuration, and outcome summary. |
| `entity_resolution_decisions` | Exactly one decision row per resolution run (`resolution_run_id` is UNIQUE), recording the outcome, matched company, method and confidence, with the per-candidate set and rationale carried in `candidate_company_ids` and `reasons`, so a match can be re-read and audited rather than re-derived. |
| `entity_resolution_consumptions` | Binds a resolution decision to the workflow run that consumed it, so a downstream write can be traced to the exact match that justified it. |
| `memo_citations` | The claim-to-evidence edges of one memo. Append-only, and lineage-guarded so a memo cannot cite outside its frozen evidence snapshot. |
| `signal_sources` | The operator-governed source watchlist driving `source-watch`/`source-scan`, including cadence, owner, confidentiality, enabled state, and last-scan state. |

`memo_citations`, like the other history tables, is append-only. `signal_sources`
is confidentiality-gated: model lanes are capped at the `internal` ceiling and
cannot re-enable, reclassify, or re-own an entry an operator has disabled.

## Audit and retention

`audit_events` records actor, transaction/request/run, generic entity identity, compact before/after state, details, and time. A trigger rejects update, delete, and truncate even for the owner. The runtime receives only `SELECT` and `INSERT`.

Domain tables use restrictive foreign keys so evidence and decision lineage cannot disappear through cascading runtime operations. Runtime delete/truncate is denied globally. Retention is implemented by an approved operator process that first exports required audit lineage and then uses a reviewed migration or owner procedure; it is never an agent command.

Audit details must exclude raw approval tokens, secrets, private document bodies, and model/provider credentials.

## Runtime privilege boundary

`openclaw_runtime` is `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE`, and `NOINHERIT`. The grants migration:

- removes public table, sequence, function, database-create, and temporary-table privileges;
- grants only database connect and schema usage;
- grants explicit ordinary domain-table `SELECT`, `INSERT`, and `UPDATE`;
- grants workflow, approval, and outbox tables `SELECT`/`INSERT` but no raw `UPDATE`, and notification attempts `SELECT` only; their lifecycle changes use fixed-search-path, owner-owned `SECURITY DEFINER` functions;
- grants audit `SELECT` and `INSERT` only;
- grants sequence use required by identity columns;
- grants only the reviewed workflow, approval, and notification lifecycle functions;
- grants no `DELETE`, `TRUNCATE`, DDL, schema creation, role management, ownership, or grant authority; and
- gives future objects no automatic runtime privilege.

The runtime role is trusted application infrastructure, not a hostile-tenant boundary. Specialists do not receive its credentials or direct SQL tools. Agent-originated typed writes occur only through one of the eighteen reviewed fixed `vcrun` workflows; operations outside those workflows require the non-allowlisted operator helper.

## Transaction rules

The application must use short transactions and a finite `connect_timeout`, `statement_timeout`, and `lock_timeout`. The role initializer additionally pins `statement_timeout = 30s`, `lock_timeout = 10s`, and `idle_in_transaction_session_timeout = 120s` on the runtime role itself (re-applied on every credential reconcile), so a runaway statement or an abandoned transaction fails instead of wedging the deterministic lane. Each unit below is atomic:

- intake lead plus provider-event dedupe;
- append-only outer workflow-request claim before intake business mutations;
- artifact upsert plus lead-artifact provenance;
- fact plus all source/document locators;
- compiled-truth snapshot plus fact ledger;
- evaluation plus all criterion rows;
- memo version plus lineage;
- approval consumption plus governed operation;
- notification claim and attempt creation;
- notification outcome plus attempt completion; and
- workflow terminal transition plus audit.
- trusted-context consumption plus the scoped document/preference operation;
- preference observation plus threshold activation; and
- preference forget marker, current-value transition, and audit.

On constraint, serialization, or connection failure, return structured JSON and a non-zero process status. Retry only idempotent operations. Never retry an external side effect until its provider idempotency/receipt state is reconciled.

## Required database gate

Before release or upgrade, the gate must prove all of the following on a disposable database and again on the target PostgreSQL major version:

1. migrations apply in order and a second application is clean;
2. real file checksums register and a mismatched checksum is rejected;
3. runtime can read/insert/update permitted domain state but cannot delete, truncate, create schema/table/temp table, alter, or mutate audit/migration rows;
4. the same artifact attaches to two leads while duplicate lead/artifact attachment is rejected;
5. typed-value, score-band, missing-criterion, period, and foreign-key negatives fail;
6. current compiled truth rejects an uncited or unverified fact;
7. workflow version conflict and terminal/cancel overwrite fail;
8. approval wrong token/scope/action/target/payload, expiry, and replay fail; rollback restores consumability;
9. concurrent notification claims select one worker, stale claims fail, retries are bounded, and provider IDs deduplicate; and
10. workflow request payload changes fail before business mutation and one
    logical inbound request cannot bind a second extraction;
11. blocking contradictions and identity conflicts remain in compiled truth
    and override contrary caller booleans at final evaluation; and
12. trusted principals remain isolated, group preference changes fail,
    capability replay fails, explicit/inferred thresholds hold, and forgetting
    resets the inference denominator; and
13. backup and restore preserve counts, hashes, constraints, grants, preference
    state, forget markers, and audit rows.

Static parsing or a successful `py_compile` is not a substitute for this database gate.
