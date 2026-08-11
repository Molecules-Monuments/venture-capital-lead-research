# Task Flow and Workflow State

Policy version: `3.0`

## State authorities

| State | Authority | Durable location |
| --- | --- | --- |
| Flow status, wait metadata, linked tasks, sticky cancel intent, flow revision | OpenClaw Task Flow | `$OPENCLAW_STATE_DIR/state/openclaw.sqlite` |
| Workflow continuation and approval index | Lobster | `$LOBSTER_STATE_DIR` |
| Leads, evidence, evaluations, approvals, notification intent, business workflow audit | Postgres through `vcops` | Postgres and `workflow_runs` |
| Verified channel principals and bounded per-user preferences | Postgres through capability-bound `vcops` operations | Postgres preference tables and append-only audit |

These stores are independent. Task Flow success does not prove a Postgres
commit. Postgres success does not prove a detached task settled. Lobster state
is a continuation mechanism, not business authority or durable memory.

## Enforced execution boundary

The direct `lobster` agent tool is disabled. Lobster shell steps execute through
`/bin/sh -lc`; direct tool parameters can accept an inline pipeline or arbitrary
workflow path, and OpenClaw exec approvals do not interpose on that nested
shell. Agent instructions cannot make this broad authority safe.

Agents may ask the data steward to execute only the exact approved runner:

```text
/workspaces/vc-chief/vc/bin/agent/vcrun run <evaluate-lead|inbound-intake|inbound-text-intake|outbound-scout|runtime-preflight|document-ingest|document-lead-intake|preference-observe|preference-forget|evidence-record|contradiction-record|trajectory-record|memo-record|source-watch|source-unwatch|source-scan|orchestration-record|proposal-record> --args-json <object>
/workspaces/vc-chief/vc/bin/agent/vcrun dry-run <same-fixed-selector> --args-json <object>
/workspaces/vc-chief/vc/bin/agent/vcrun doctor
/workspaces/vc-chief/vc/bin/agent/vcrun version
```

`vcrun` maps the selector to a reviewed file and rejects unknown selectors,
`--file`, paths, inline pipelines, arbitrary commands, passthrough arguments,
cwd/env overrides, timeout/output overrides, NUL characters, JSON larger than
32 KiB, any single argument value longer than 16 384 characters, non-string
values, missing required keys, and extra keys. The runner owns the time and
output limits. The per-value ceiling is the lower of the two and is the one a
long `memo_markdown`, `evidence_json` or `citations_json` normally hits first:
the refusal is `<field> exceeds 16384 characters`. The payload ceiling is
nevertheless checked earlier — before the JSON is parsed — so a value big
enough to carry the whole object past 32 KiB is refused as `args JSON exceeds
32768 bytes` instead, naming the payload rather than the field. Either refusal
is raised before any step runs, so nothing is written and the same idempotency
key stays usable.

Only an authenticated operator environment may use the separate control
binary, which is not present in any agent exec allowlist:

```text
/workspaces/vc-chief/vc/bin/vcrun-control resume --id <8-hex-approval-id> --approve yes
/workspaces/vc-chief/vc/bin/vcrun-control resume --id <8-hex-approval-id> --approve no --run-id <postgres-run-id> --expected-revision <positive-integer>
/workspaces/vc-chief/vc/bin/vcrun-control resume --id <8-hex-approval-id> --cancel --run-id <postgres-run-id> --expected-revision <positive-integer>
```

`vcrun` itself has no resume, token, decision, or cancel option. The control
launcher requires a nonempty inherited `VCOPS_OPERATOR_ID`, then rebuilds a
minimal environment containing only that validated stable identity. The
gateway never sets it and the control path is not allowlisted, so agents cannot
approve or resume their own run. Tokens must not enter chat, logs, Slack,
Microsoft Teams, Discord, or Telegram. Agent-facing output recursively redacts the bearer token and retains
only the eight-hex approval ID used by the authenticated control wrapper.

Neither runner accepts or forwards a caller-supplied database URL, database
password, or approval pepper. The immutable `vcops` launcher selects fixed
runtime mode, a hardcoded internal DSN, and Docker secret files.

## Postgres lifecycle and reconciliation

Each reviewed workflow declares and uses one caller-generated
`idempotency_key` and follows this business lifecycle:

1. preflight;
2. document workflows preview their bounded document or verify their prior extraction;
3. inbound/outbound/document workflows append an immutable canonical `workflow_requests` claim
   for every outer argument (plus the inspected SHA and verified principal/channel provenance where applicable), before any
   business mutation;
4. idempotent lead/company materialization when their IDs are needed by the run;
5. `vcops workflow-start` returns `queued` at record revision 1;
6. `vcops workflow-transition --status running` uses that exact revision;
7. bounded deterministic work, with document extraction globally bound to its
   workflow-request row; preference workflows consume a scoped, replay-protected capability and append preference evidence/audit;
8. `vcops workflow-transition --status succeeded` uses the current revision.

A command error stops Lobster. There is no `finally` step, so a Postgres row may
remain `running` when execution bypasses or loses the fixed runner. Fixed
`vcrun` reconciles bounded timeout, output-limit, invalid-output, and step
failure classes through the exact workflow/idempotency lineage and accepts
only `not_started`, `already_failed`, or `transitioned_failed`; a present row
must be `failed`. If that reconciliation fails, the runner surfaces failure and
does not claim cleanup. For manual recovery, capture the `run_id` and
`record_version` from helper JSON or the evaluation approval item. Reconcile
with the same logical idempotency key and latest revision:

- expected failure: transition to `failed` with a bounded error;
- missing authoritative backing after investigation: transition to `lost`;
- operator/user cancellation: call `workflow-cancel`;
- never start a new logical run to conceal an unfinished one.

Cancellation is terminal. A late result may not overwrite Postgres
`cancelled`, and a sticky Task Flow cancellation refuses new managed child
tasks and cancels active ones. Rejection of `evaluate-lead` must leave the
Lobster continuation deleted and the Postgres run explicitly `cancelled`.

## Task Flow contract

Task Flow statuses are `queued`, `running`, `waiting`, `blocked`, `succeeded`,
`failed`, `cancelled`, and `lost`. Every mutating managed-flow call is
optimistic. Carry the returned revision forward. On `revision_conflict`, re-read
the flow and decide again; never guess or increment locally.

In the pinned `2026.7.1` plugin SDK the mutation-capable runtime is
`api.runtime.tasks.managedFlows`; `api.runtime.tasks.flows` and
`api.runtime.tasks.runs` are read-only views, `api.runtime.tasks.flow` is a
**deprecated alias** for `managedFlows`, and `api.runtime.taskFlow` is a legacy
runtime alias. OpenClaw may create a mirrored one-task flow for detached
data-steward work. Standalone `vcrun` does not create a managed Task Flow and
must not claim one.

The upstream direct Lobster tool also has managed fields:

- run: `flowControllerId`, `flowGoal`, optional `flowStateJson`,
  `flowCurrentStep`, `flowWaitingStep`;
- resume: `flowId`, current `flowExpectedRevision`, optional
  `flowCurrentStep`, `flowWaitingStep`, plus token/approval ID and Boolean
  decision.

This is compatibility information, not an enabled Version 3 route. In pinned
OpenClaw v2026.7.1, a successful Lobster `cancelled` envelope is mapped by the
managed adapter to Task Flow `finish`, which can mislabel rejection as
`succeeded`. The direct resume schema also supplies a Boolean decision but no
hard authenticated approver binding. Do not enable managed Lobster until both
defects are corrected and live-tested.

## Approval boundary

A Lobster pause is a resumable checkpoint, not authorization for Slack, Teams,
email, payments, deletions, or any other external effect. Such an effect must
still atomically consume a matching, scoped, expiring, one-time Postgres
approval and use the notification/outbox policy. `approval-decide` is
operator-only and never appears in a Lobster file.

## Persistence and recovery

Compose sets:

```text
LOBSTER_STATE_DIR=/home/node/.openclaw/lobster/state
```

The default `/home/node/.lobster/state` is outside the read-only gateway's
writable volume. The configured directory is covered by the quiesced
OpenClaw-state archive together with Task Flow SQLite. The package lifecycle
lock stops gateway and CLI while it captures that archive, Postgres (including
preference memory), inbox originals, and the named quarantine volume as one recovery
window. Its local-artifact inventory must resolve every database
inbox/quarantine URI to the staged bytes and hash.

After restore:

1. verify archive checksums, package version, safe archive paths, and the local
   artifact inventory before any destructive change;
2. prove a disposable database restore, then run `openclaw doctor`,
   `openclaw tasks audit`, and maintenance preview on the restored target;
3. list and inspect active flows;
4. reconcile every non-terminal Postgres workflow;
5. allow operator resume only when Lobster state exists, the business action is
   still valid, and any Task Flow revision is current.

Never replay an external effect solely because a flow is `waiting`, `blocked`,
or `lost`. Require provider and database idempotency evidence.

## Inspection

The chief has no `exec` or gateway tool and cannot run shell commands; the data
steward's narrow exec allowlist is `vcops` + `vcrun` only and does not include
`openclaw tasks`. So no agent runs the CLI below — and the chief has no Task
Flow *read* surface either. `api.runtime.tasks.*` is the plugin-SDK runtime
handed to a plugin's `register(api)`, not an agent tool. This deployment loads
the image-owned `vc-trusted-context` extension — which registers hooks and no
flow surface — alongside `web-readability`, the only other plugin the renderer
allows unconditionally, plus whichever of the selected model-provider plugin
(`openai` or `ollama`; a custom provider contributes none), the selected
web-search and web-fetch provider plugins, and the selected channel plugin this
deployment renders; none of them contributes an agent-callable Task Flow tool, and
`vc-chief`'s tool allowlist carries no Task Flow reader. Its Task
Flow awareness is therefore entirely second-hand: flow status, linked tasks,
sticky cancel intent, and the current flow revision reach it only as an
operator-supplied export attached to the request (`HEARTBEAT.md` step 2), and it
reports `not_observable` when that export is absent. The orchestration audit trail
(`delegation_eval`/`return_assessment`/`chief_output`) is persisted through the
`orchestration-record` fixed workflow together with the Task Flow correlation
handles (`flow_id`/`flow_revision`/`task_id`), so those handles are queryable
columns on `orchestration_audit`, not an opaque payload.

The following are authenticated-operator commands (like `vcrun-control`), run
from an operator environment, never by any agent:

```bash
openclaw tasks flow list --json
openclaw tasks flow show <flow-id-or-owner-key> --json
openclaw tasks flow cancel <flow-id-or-owner-key>
openclaw tasks audit
openclaw tasks maintenance
```

At most three child agents may run at once for one lead. Deeper work uses
sequential, gated waves. Cron and channel-triggered workflows remain disabled
until retained live evidence proves fixed-runner rejection tests, Postgres
lifecycle and revision conflicts, checkpoint/restart/operator-resume,
rejection cleanup, Task Flow audit/maintenance, and backup/restore.
