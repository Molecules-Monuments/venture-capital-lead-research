# Version 3 Workflow Operations

Version 3 contains eighteen fixed Lobster workflow files. Every executable step
calls the image-owned internal launcher
`/workspaces/vc-chief/vc/bin/vcops-workflow`. No workflow accepts a
caller-supplied command, invokes a communication provider, or uses
`openclaw.invoke`.

## Compatibility and authority

The files target OpenClaw `2026.7.1` and Lobster `2026.6.11`. Pinned-source and
image tests establish that workflow arguments become quoted
`LOBSTER_ARG_<NAME>` environment values; nested step JSON references, `run`,
`env`, `stdin`, `condition`, `timeout_ms`, and approval steps are supported;
and file steps execute through Lobster's shell.

That last property is why direct Lobster is disabled. A general Lobster agent
tool accepts inline pipelines and file paths, and its nested shell is not the
same as OpenClaw's outer exec approval. No agent receives the general tool.

Only data steward can invoke the exact `vcrun` launcher. `vcrun` maps a closed
selector to an immutable workflow, validates an exact JSON contract, constructs
a minimal environment, enforces time/output bounds, normalizes output, redacts
secret-like fields, and performs bounded workflow-failure reconciliation.

## Commands

```text
/workspaces/vc-chief/vc/bin/agent/vcrun run <selector> --args-json '<object>'
/workspaces/vc-chief/vc/bin/agent/vcrun dry-run <selector> --args-json '<object>'
/workspaces/vc-chief/vc/bin/agent/vcrun doctor
/workspaces/vc-chief/vc/bin/agent/vcrun version
```

Selectors are `runtime-preflight`, `outbound-scout`, `inbound-intake`, `inbound-text-intake`,
`document-ingest`, `document-lead-intake`, `preference-observe`,
`preference-forget`, `evaluate-lead`, `evidence-record`,
`contradiction-record`, `trajectory-record`, `memo-record`, `source-watch`,
`source-unwatch`, `source-scan`, `orchestration-record`, and `proposal-record`.

`vcrun` rejects unknown selectors, paths, `--file`, inline pipelines, arbitrary
commands, passthrough flags, cwd/env overrides, caller time/output overrides,
duplicate JSON keys, non-object JSON, NULs, input above 32 KiB, wrong value
types, missing fields, extra fields, invalid domain/BIGINT/preference values,
and paths outside the exact permitted intake root.

The agent-facing runner does not accept `DATABASE_URL`, DB passwords, provider
keys, approval secrets, resume tokens, or an operator identity. The internal
launcher uses fixed runtime mode and Docker secret files.

## Inventory

All values are strings and every listed field is required unless explicitly
marked optional.

| Selector | Purpose | Exact fields |
| --- | --- | --- |
| `runtime-preflight` | Prove the installed helper/database boundary | `idempotency_key` |
| `outbound-scout` | Claim, resolve, and persist a candidate already selected by research | `idempotency_key`, `company_name`, `company_domain`, `lead_title` |
| `inbound-intake` | Authenticated host-operator `/inbox` preview, claim, lead creation, and extraction | `idempotency_key`, `lead_title`, `company_name`, `company_domain`, `document_path`, `channel_provider`, `channel_account_id`, `channel_event_id` |
| `inbound-text-intake` | Create a lead from a text-only inbound signal (no document) and bind its origin subtype | `idempotency_key`, `lead_title`, `company_name`, `company_domain`, `origin_subtype` |
| `document-ingest` | Verify a current channel attachment capability, claim exact bytes, snapshot, and extract | `idempotency_key`, `document_path`, `trusted_context` |
| `document-lead-intake` | Bind a verified channel extraction to an exact principal, company, and lead | `idempotency_key`, `trusted_context`, `extraction_id`, `lead_title`, `company_name`, `company_domain` |
| `preference-observe` | Record one supported direct-message preference observation and activate under policy | `idempotency_key`, `trusted_context`, `preference_key`, `preference_value`, `observation_kind` |
| `preference-forget` | Mark one supported preference forgotten for the verified principal | `idempotency_key`, `trusted_context`, `preference_key` |
| `evaluate-lead` | Load, prequalify, pause, compile truth, and persist a final evaluation | `idempotency_key`, `lead_id`, `criteria_json`, `decision_context_json` |
| `evidence-record` | Persist one research claim with provenance as `submitted_claim`, then attempt the deterministic corroboration-gated promotion | `idempotency_key`, `lead_id`, `evidence_json` |
| `contradiction-record` | Record the deterministic contradiction classification for two persisted facts | `idempotency_key`, `lead_id`, `left_fact_id`, `right_fact_id`, `severity` |
| `trajectory-record` | Record the deterministic trajectory classification for two persisted facts | `idempotency_key`, `lead_id`, `left_fact_id`, `right_fact_id` |
| `memo-record` | Persist the memo produced from the frozen, human-approved snapshot (lands as `draft`; citations are trigger-confined to the snapshot) | `idempotency_key`, `lead_id`, `evaluation_id`, `compiled_truth_id`, `memo_title`, `memo_markdown`, `citations_json`, `evidence_hash` |
| `source-watch` | Register or re-enable one watched surveillance source (the "monitor this website" path); the workflow lane cannot re-enable an operator-disabled entry, lower a stored confidentiality, or change ownership | `idempotency_key`, `source_name`, `source_uri`, `source_class`, `cadence`, `thesis_relevance`, `expected_signal` |
| `source-unwatch` | Disable one watched source without deleting its history | `idempotency_key`, `source_uri` |
| `proposal-record` | Persist one governance proposal (schema change / source policy / skill candidate) for operator review; applies nothing | `idempotency_key`, `proposal_kind`, `title`, `summary`, `content_json` |
| `orchestration-record` | Persist one orchestration/delegation audit entry (delegation_eval / return_assessment / chief_output) for a lead's research run | `idempotency_key`, `lead_id`, `record_kind`, `specialist`, `payload_json`; optional Task Flow correlation handles `flow_id`, `task_id`, `flow_revision` (empty string persists as NULL) |
| `source-scan` | Atomically claim the enabled sources due this cycle (by cadence) and return the worklist for research | `idempotency_key`, `limit` (1–500) |

The outer runner cap is 360 seconds and 512 KiB output. Individual helper
steps use lower operation-specific limits.

The inner payload contracts are reviewed model-facing documentation: the
`evidence_json` field set and researcher-packet mapping live in
`workspaces/shared-skills/data-persistence/SKILL.md`, and the `citations_json`
element contract lives in `workspaces/shared-skills/memo-writing/SKILL.md`.

### Manual versus channel documents

`inbound-intake` is the optional authenticated host-operator lane. Its path
must be an absolute normalized child of `/inbox` and `channel_provider` must be
`manual`. Channel attachments cannot be tunneled through that workflow.

`document-ingest` is the channel lane. Its path must be a direct child of
`/home/node/.openclaw/media/inbound` and the signed current-turn capability
must contain the exact path-hash ingest/read scopes. It previews before
mutation, commits the canonical path/byte hash request, creates a workflow run,
then snapshots and extracts.

`document-lead-intake` consumes a separately scoped association operation for
the same verified provider/account/sender principal. It globally binds the
extraction to one lead association request and preserves original filename,
provider event, and sender identity.

Both lanes support PDF, PPTX, XLSX, and CSV only. Helper checks and resource
limits, not the filename or model, determine acceptance.

### Preference workflows

The supported keys/values are defined in `vcops.py`. A trusted-context token
must include the exact preference scope. Writes and forgets require a verified
direct session; groups fail before consuming the capability.

An explicit observation activates at once. An inferred observation activates
after three distinct provider events for the same principal/key/value/kind
after the latest forget marker. Replays do not add evidence. Forgetting writes
a cutoff even when no active row exists, so pre-forget observations cannot
reactivate a preference.

`preference-lookup` is a read-only helper call, not a Lobster workflow, because
it does not create a business workflow mutation. It still consumes one signed
read scope for the current event/operation.

### Outbound and evaluation

`outbound-scout` never browses. Probabilistic discovery and evidence research
happen before this deterministic persistence lane.

`criteria_json` and `decision_context_json` are JSON-object strings inside the
outer JSON object. Serialize twice; never concatenate chat text in a shell.
Rubric weights total 100, scores use the fixed schema, missing quality remains
null with zero contribution under the fixed denominator, and coverage remains
separate.

## Request claims, idempotency, and replay

Each mutating workflow commits a canonical request claim before its first
domain mutation. A new logical operation receives a new opaque idempotency key.
The same logical retry reuses the same key and exactly the same inputs. Same key
plus changed arguments, document path/hash, extraction, or principal fails
closed.

Channel capabilities add a second layer: `(nonce, scope)` is recorded in
PostgreSQL. The same operation may be idempotently observed again, but a
different operation key, principal, or provider event using the same
nonce/scope fails as `trusted_context_replay`.

## Evaluation checkpoint

`evaluate-lead` pauses before compiled-truth or final evaluation persistence.
The pause exposes only an eight-hex correlation ID. The long resume token never
appears in an agent result.

Operator continuation is separate and not agent-allowlisted. The wrapper lives
inside the gateway image, so run it through `compose exec` from the package
directory on the deployment host:

```sh
docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env \
  exec -e VCOPS_OPERATOR_ID=<stable-operator-id> openclaw-gateway \
  /workspaces/vc-chief/vc/bin/vcrun-control resume --id <approval-id> --approve yes
```

The wrapper accepts these forms:

```text
vcrun-control resume --id <approval-id> --approve yes
vcrun-control resume --id <approval-id> --approve no --run-id <postgres-run-id> --expected-revision <n>
vcrun-control resume --id <approval-id> --cancel --run-id <postgres-run-id> --expected-revision <n>
```

`VCOPS_OPERATOR_ID` identifies the human taking the action, so it is passed per
invocation with `exec -e` and is deliberately **not** an `.env` key —
`check_env.py` rejects it there as an unknown variable. Rejection/cancel first
requires the exact Postgres run to reach `cancelled`; only then may Lobster
consume destructive continuation. A failure before that proof leaves Lobster
state intact.

The proposed calculation is provisional. Final database persistence derives
identity and blocking-contradiction readiness from authoritative lineage,
records caller mismatch, and applies the database result.

This checkpoint is an internal review, not external-action authorization. A
future external effect would still need a scoped, expiring, identity-bound,
payload-hash-bound PostgreSQL approval consumed atomically with the durable
action intent.

## Failure and recovery

Lobster stops at the first command error and has no `finally` step. A failure
after a run becomes `running` can leave business state non-terminal. The runner
handles its bounded timeout, output-limit, invalid-output, and step-failure
classes by calling `workflow-reconcile-failure` with the exact fixed workflow
ID and idempotency key. Only `not_started`, `already_failed`, or
`transitioned_failed` is accepted as cleanup. It never relabels succeeded,
cancelled, or lost work.

For an incident:

1. stop new retries and retain helper/runner JSON;
2. inspect the same business run and any mirrored Task Flow;
3. issue sticky Task Flow cancellation if active specialist work must stop;
4. re-read the current Postgres revision and terminal/idempotency state;
5. reconcile the same run rather than creating a replacement key;
6. verify content-addressed document bytes and association state; and
7. run Task Flow audit/maintenance before a controlled retry.

An unchanged retry may return existing request, lead, extraction, association,
preference audit, or run records. That is expected idempotency, not duplicate
work.

## Task Flow relation

Detached specialists may appear as mirrored OpenClaw Task Flows. Standalone
`vcrun` does not create a managed Lobster-backed Task Flow. The upstream
managed adapter is not enabled because its cancellation/rejection mapping and
approver identity are not this application's business contract.

Task Flow success is orchestration evidence only. Workflow success requires
the matching Postgres workflow/request records and expected domain identifiers.

## State, backup, and live gate

`LOBSTER_STATE_DIR=/home/node/.openclaw/lobster/state` places continuation in
the writable OpenClaw state volume. PostgreSQL is separate. Backup quiesces
consumers and captures both in one recovery window; restore verifies both
before traffic and reconciles non-terminal runs.

Before a live deployment relies on workflows, retain evidence that:

- only data steward can execute exact `vcrun` and direct Lobster is absent;
- all eighteen dry runs match reviewed graphs and command contracts;
- all eighteen representative live operations reach the expected Postgres state
  exactly once;
- preference principals, group denial, forget cutoffs, and replay are correct;
- supported and hostile channel documents take the expected path;
- evaluation pause survives restart and an authenticated operator resumes or
  rejects once;
- a revision conflict fails without state loss;
- Task Flow audit has no unresolved issue; and
- backup/restore preserves Postgres, Task Flow, Lobster, preference state, and
  document artifact identity.

The workflows do not send Slack, Teams, Discord, or Telegram messages and do
not authorize outreach. Cron remains disabled unless separately designed,
reviewed, and commissioned.
