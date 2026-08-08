# Task Flow and Lobster compatibility contract

Status: Version 3 package gates passed; exact live deployment gate not yet passed  
Audit date: 2026-07-17  
OpenClaw target: `v2026.7.1`, commit `2d2ddc43d0dcf71f31283d780f9fe9ff4cc04fe4`  
Embedded Lobster runtime: `@clawdbot/lobster@2026.6.11`, source tag `v2026.6.11`, commit `86b8cc20a867f18c08ae8e3f4fec9ee7d52bf8c9`

Source citations below use the prefixes `upstream_openclaw/` and
`upstream_lobster/` for paths inside those two upstream repositories at the
commits named above. They are not files in this package: read them at
`github.com/openclaw/openclaw` and `github.com/openclaw/lobster` at those
commits. Line numbers are as of the audit date.

## Release verdict

The package's source, configuration, fixed-runner, negative-boundary, and
offline lifecycle contracts pass the retained Version 3 release gates. The
official OpenClaw release image prunes the optional Lobster extension, so the
derived image installs `@clawdbot/lobster@2026.6.11` explicitly from
`runtime-packages/package-lock.json` with `npm ci` and exposes only its fixed
CLI to `vcrun`. Source audit also found that Lobster's default
`/home/node/.lobster/state` would be unwritable under the read-only container
root. Compose therefore sets
`LOBSTER_STATE_DIR=/home/node/.openclaw/lobster/state` for the gateway and CLI,
placing it on the persistent writable state volume. A concrete deployment is
**not entitled to claim a live approval/resume path** until the exact
write/restart/approval/resume/restore tests below pass on that target with
retained evidence.

Version 3.0 selects this production boundary:

- No agent receives the upstream `lobster` tool. It must be absent from global `tools.alsoAllow` and from every per-agent effective allowlist. The package may remain installed as the pinned runtime, but its free-form OpenClaw tool is disabled by policy.
- The only agent-facing Lobster entry point is the exact exec-allowlisted `/workspaces/vc-chief/vc/bin/agent/vcrun`, invoked by `data-steward`. `vcrun` maps a small workflow identifier to an immutable, reviewed workflow file; it never accepts a workflow path, inline pipeline, command text, working directory, environment override, arbitrary Lobster option, resume token, or approval decision.
- Resume and cancel are available only through the separate operator surface `/workspaces/vc-chief/vc/bin/vcrun-control`. That executable is not in OpenClaw tools or exec approvals and must run only from an authenticated administrative path with a stable operator identity and retained audit event.
- Managed Lobster/Task Flow mode is disabled. `vcrun` must not pass `flowControllerId`, `flowGoal`, `flowId`, or `flowExpectedRevision`.
- Lobster approval pauses are control-flow only. The `evaluate-lead` pause is an internal human-review checkpoint before persisting the evaluation; it is not authorization for messaging, outreach, disclosure, or another external action. Any external effect remains unavailable unless a dedicated `vcops` command validates and atomically consumes a scoped, expiring, one-time Postgres approval inside that exact operation. A Lobster approval ID, token, or `approve` decision cannot grant external-action authority.

This selection is necessary because the upstream `lobster` tool accepts a free-form pipeline, includes an `exec` command, and workflow `run`/`command` steps spawn a shell inside the gateway process. OpenClaw's ordinary exec allowlist and `exec-approvals.json` do not mediate those child processes. Enabling the tool for an agent would therefore give that agent effective gateway-container shell authority. Read-only mounts reduce persistence risk, but do not prevent credential reads, network access, database access through environment variables, or mutation of writable state.

The selected boundary is a required release property, not merely documentation. Until configuration, the `vcrun` implementation, fixed workflows, and negative tests all prove it, G5 remains failed.

## Authority boundaries

These systems have separate responsibilities and must not be made competing sources of truth.

| System | Authoritative for | Not authoritative for |
|---|---|---|
| Postgres | companies, leads, evidence, evaluations, memos, application approvals, notification outbox, application workflow ledger | OpenClaw task delivery and gateway orchestration internals |
| OpenClaw Task Flow | operational multi-step orchestration, child-task linkage, wait state, controller revision, cancellation intent | lead facts, investment decisions, notification authorization |
| Lobster | execution of a deterministic pipeline and its local pause/resume continuation | user identity, durable business authorization, lead lifecycle |
| OpenClaw memory | agent working context and retrieval | canonical company/lead/evidence records |

Do not copy Task Flow rows into Postgres as a second Task Flow authority. Store only a correlation identifier where the business audit needs one. Do not infer business completion solely from an OpenClaw flow's terminal status; check the business command result and committed Postgres state.

## Pinned-source evidence

The OpenClaw plugin package pins the embedded runtime exactly: `extensions/lobster/package.json:1-12` declares `@openclaw/lobster@2026.7.1` and `@clawdbot/lobster@2026.6.11`; `extensions/lobster/npm-shrinkwrap.json:15-31` records the tarball, integrity, and Node `>=22` requirement. The exact research checkouts are:

- `Version_2/intermediate/upstream_openclaw` at the OpenClaw commit above.
- `Version_2/intermediate/upstream_lobster` at the Lobster commit above.

Those checkouts are audit evidence, not release payload.

## Lobster operational contract

### Exposure and isolation

- The tool is optional and the factory returns no tool at all when `ctx.sandboxed` is true (`upstream_openclaw/extensions/lobster/index.ts:6-23`). Adding Lobster to sandbox tool policy does not override this behavior.
- A usable Lobster call is therefore a non-sandboxed, or "ground/host", workflow. There is no upstream `unsafe`, `allowGround`, or workflow-command allowlist flag in the plugin manifest; the plugin config schema has no properties (`upstream_openclaw/extensions/lobster/openclaw.plugin.json:1-20`).
- The embedded runtime executes in the gateway process, not a separate Lobster subprocess (`upstream_openclaw/docs/tools/lobster.md:69-75`). Workflow shell steps resolve to `/bin/sh -lc <command>` on Unix and use `child_process.spawn` with the gateway environment and selected working directory (`upstream_lobster/src/shell.ts:1-33`; `upstream_lobster/src/workflows/file.ts:2764-2818`).
- Consequently, Lobster shell execution bypasses OpenClaw `tools.exec` policy and `exec-approvals.json`. A Lobster `approval:` step is a pipeline pause, not enforcement by OpenClaw's exec approval subsystem.
- The plugin schema provides no workflow-path or command allowlist (`upstream_openclaw/extensions/lobster/openclaw.plugin.json:1-20`). The OpenClaw tool accepts caller-supplied `pipeline` and file inputs (`upstream_openclaw/extensions/lobster/src/lobster-tool.ts:233-291`), and absolute workflow paths are accepted by the runner (`upstream_openclaw/extensions/lobster/src/lobster-runner.ts:227-269`). Tool policy therefore cannot turn the upstream tool into the fixed-workflow interface required here.
- No production agent, including `vc-chief` and `data-steward`, may receive the direct `lobster` tool. `data-steward` receives only exact-path `exec` permission for the reviewed helper surfaces; every other agent remains unable to execute Lobster.

### Fixed `vcrun` boundary

The agent-facing command contract is intentionally narrower than the upstream CLI:

```text
/workspaces/vc-chief/vc/bin/agent/vcrun run <fixed-id> \
  --args-json <single-JSON-object>

/workspaces/vc-chief/vc/bin/agent/vcrun dry-run <fixed-id> \
  --args-json <single-JSON-object>

/workspaces/vc-chief/vc/bin/agent/vcrun doctor
/workspaces/vc-chief/vc/bin/agent/vcrun version
```

`vcrun` has no `resume` or `cancel` subcommand. Operator control is physically separated:

```text
/workspaces/vc-chief/vc/bin/vcrun-control resume \
  --id <8-hex-approval-id> \
  --approve yes

/workspaces/vc-chief/vc/bin/vcrun-control resume \
  --id <8-hex-approval-id> \
  --approve no \
  --run-id <postgres-run-id> \
  --expected-revision <n>

/workspaces/vc-chief/vc/bin/vcrun-control resume \
  --id <8-hex-approval-id> \
  --cancel \
  --run-id <postgres-run-id> \
  --expected-revision <n>
```

The operator wrapper's internal mapping follows the pinned Lobster CLI contract: upstream accepts `resume --id <approval-id> --approve yes|no` or `--cancel` and resolves that ID through the protected state index (`upstream_lobster/src/cli.ts:519-541`; parsing/resolution in `upstream_lobster/src/resume.ts:24-43,90-149`). On cancel, the CLI removes persisted state/index and returns `status: cancelled`; on workflow resume it reloads the saved state and decision. The ID is a correlation handle, not authentication, so the non-allowlisted wrapper still requires the stable administrative operator identity.

`vcrun-control` must not appear in `exec-approvals.json` or any agent tool contract. It must require an authenticated, stable operator identity supplied by the administrative control plane, not caller-controlled OpenClaw exec environment, and record only non-secret correlation/decision metadata. Agent-facing `vcrun` parses the final Lobster JSON, recursively redacts secret/token/password/credential fields, and returns only the approval ID; the bearer token must never enter an agent result or log. For the current `evaluate-lead` workflow this controls an internal review checkpoint; it is not an external-action authorization. A future workflow that performs an external effect must still call a dedicated `vcops` operation that atomically consumes the matching Postgres authorization.

`vcrun` must satisfy all of these invariants:

- accept only an enumerated workflow ID and map it internally to one immutable file under `/workspaces/vc-chief/vc/workflows`; reject file paths, `/`, `..`, URI-like values, symlinks outside the inventory, and unknown IDs;
- accept exactly one JSON object, reject duplicate keys, unknown keys, non-scalar values unless explicitly schema-approved, normalized argument-name collisions, and values outside per-workflow type/length/pattern limits;
- invoke the pinned Lobster runtime without a shell and without allowing caller-supplied pipeline text, command text, `cwd`, environment, executable, token, response JSON, timeout/output override, or trailing arguments;
- discard caller-controlled OpenClaw exec environment; construct a minimal fixed environment and fixed writable `LOBSTER_STATE_DIR`, obtain database credentials only from the deployment's fixed secret path/control plane, retain the immutable workflow directory read-only, bound wall-clock time and captured output outside Lobster as well as inside the workflow, and emit one stable JSON envelope;
- keep run identifiers and secrets out of logs; never accept the long bearer resume token or a decision through the agent-facing interface;
- never pass managed Task Flow fields to OpenClaw's Lobster adapter;
- ensure every workflow shell step invokes only the exact immutable `vcops` path. A static release validator must reject any other executable, shell metacharacter-driven control flow, raw `${arg}` substitution, `input:`, embedded `openclaw.invoke`, nested workflow, or caller-controlled `cwd`/environment key.

The exec-approval policy must list the exact immutable `vcrun` path for `data-steward` and must not list `vcrun-control`. Allowlisting only the first executable is not sufficient if `vcrun` is a permissive passthrough. The fixed parser, environment scrubbing, fixed secret/database endpoint, and negative tests are part of the security boundary. Apply the same split to `vcops`: the allowlisted agent launcher is read-only and environment-scrubbed; fixed workflow mutations use the non-allowlisted internal `vcops-workflow` child path; operator decision/control launchers must not be agent-approved.

### Invocation and workflow files

The upstream OpenClaw tool supports `action: run|resume`. A run accepts either an inline pipeline string or a workflow file whose name ends with `.lobster`, `.yaml`, `.yml`, or `.json`. A workflow-file run may receive `argsJson`; inline pipelines ignore it. A resume requires either `token` or `approvalId` and a boolean `approve` (`upstream_openclaw/extensions/lobster/src/lobster-tool.ts:233-291`; `upstream_openclaw/extensions/lobster/src/lobster-runner.ts:227-273,354-415`). These are audited upstream semantics, not an agent-facing Version 3.0 API; `vcrun` exposes only the fixed contract above.

The Lobster v2026.6.11 file shape includes:

- top-level `name`, `description`, `args`, `env`, `cwd`, `steps`, and optional `cost_limit`;
- step `id` plus exactly one execution form such as `run`/`command`, `pipeline`, `workflow`, `parallel`, `for_each`, or a synthetic approval/input step;
- `stdin`, `env`, `cwd`, `condition`/`when`, `timeout_ms`, `retry`, and `on_error` where supported.

The source types and validation begin at `upstream_lobster/src/workflows/file.ts:31-156,248-380`. For Version 3.0, keep the authoring subset intentionally smaller:

- use sequential top-level steps;
- use only these keys, which is what `scripts/validate_workflows.py` enforces as
  a closed set — anything else is a release failure, including the `command:`
  and `when:` spellings Lobster itself accepts: workflow-level `name`, `args`,
  `steps`; step-level `id`, `run`, `stdin`, `env`, `condition`, `timeout_ms`,
  `approval`;
- use a separate top-level `approval:` step before a consequential command;
- do not use nested workflow approvals or inputs, because a composed sub-workflow that pauses is rejected (`upstream_lobster/src/workflows/file.ts:1240-1256`);
- do not use `input:` in an OpenClaw-hosted workflow in this release, even though Lobster itself supports it. OpenClaw v2026.7.1 converts `needs_input` into `unsupported_status` and fails closed (`upstream_openclaw/extensions/lobster/src/lobster-runner.ts:181-190`; test at `lobster-runner.test.ts:352-380`);
- do not use embedded `openclaw.invoke`; it does not automatically inherit a gateway URL/auth context (`upstream_openclaw/docs/tools/lobster.md:179-216`).

Absolute workflow file paths are accepted by the runner even though the optional tool-level `cwd` must be relative and remain under the gateway working directory (`upstream_openclaw/extensions/lobster/src/lobster-runner.ts:146-165,227-269`). This is another reason a free-form Lobster tool is not a workflow-path allowlist.

### Arguments and shell safety

`argsJson` is parsed as JSON and defaults from the workflow's `args` map are merged with provided values (`upstream_lobster/src/workflows/file.ts:664-682`). Each resolved argument is exported as `LOBSTER_ARG_<NORMALIZED_NAME>` and the complete object as `LOBSTER_ARGS_JSON`; names are uppercased and non-alphanumeric runs become `_` (`upstream_lobster/src/workflows/file.ts:1917-1957`).

Hard authoring rules:

- Do not splice untrusted values with `${arg}` into `run`, `command`, `pipeline`, or `cwd`. That form is a raw string replacement (`upstream_lobster/src/workflows/file.ts:2014-2018`).
- Read values through a quoted environment reference, for example `"$LOBSTER_ARG_LEAD_ID"`, and validate them again in the called helper. The upstream regression test includes quotes, `$`, backticks, and command substitution characters (`upstream_lobster/test/workflow_args_env.test.ts:9-47`).
- Reject argument names that normalize to the same environment key, such as `lead-id` and `lead_id`. Upstream normalization does not reject collisions; the later value would overwrite the earlier environment variable.
- Prefer `LOBSTER_ARGS_JSON` over many shell words when the helper can accept JSON on stdin. Never use `eval`.
- Treat workflow definitions as executable code. They must be immutable in the runtime image or mounted read-only, code-reviewed, checksummed in the release manifest, and never generated from a message, uploaded document, or model output.

### Step result references

Lobster's own parser accepts `$step-id.stdout`, `$step-id.json`, and nested JSON
fields such as `$step-id.json.company.id`, with identifiers containing letters,
numbers, `_`, and `-`, and nested path elements accepting letters, numbers, and
`_` (`upstream_lobster/src/workflows/file.ts:1965-2055`).

**Version 3.0 narrows that grammar, and the narrowing is enforced.** Only
`$step-id.approved` and a *fully qualified* nested path such as
`$step-id.json.company.id` are permitted, and the exact path must additionally
appear in `SAFE_STEP_PATHS` in `scripts/validate_workflows.py`. The bare forms
`$step-id.json` and `$step-id.stdout` are release failures: they raise
`step_ref_legacy` and `step_ref_unbounded`, which fail `validate_workflows.py`
and therefore the `fixed-workflows` step of `scripts/verify_offline.py`. The
independent Lobster-semantics executor in `tests/g4/test_workflow_execution.py`
encodes the same narrow rule, and none of the eighteen shipped workflows uses a
bare form.

Operational rules:

- Prefer a fully qualified nested reference such as
  `stdin: $prior.json.workflow_run.run_id` for structured transfer and let the
  receiving helper validate its schema. A genuinely new nested path has to be
  added to `SAFE_STEP_PATHS` in the same reviewed change.
- **No reference surface fails closed on a missing field, so never rely on one to.** Measured on the pinned runtime: an `env:` value — the surface every shipped workflow uses to carry identifiers — is resolved non-strictly, so a *known* step with a missing path becomes an empty string and an *unknown* step id is left as literal text; in both cases the step still runs and the workflow returns `status: ok`. Only `condition:`, `for_each:`, and a `stdin:` that is *entirely* one reference resolve strictly, and even there the throw is for an unknown step id, not a missing path. What actually makes this fail closed is two other layers: `scripts/validate_workflows.py` rejects an unknown or out-of-order step id and any path outside `SAFE_STEP_PATHS` at release time, so the throwing case cannot ship; and the receiving `vcops` command rejects an empty or malformed required identifier at runtime. Still prefer a whole-value reference to an inline string template — a composed template hides the empty value inside otherwise valid JSON, where the helper's own validation is the only thing left to catch it.
- A shell step attempts to parse its stdout as JSON. Emit one bounded JSON value on stdout and diagnostics on stderr.
- Preserve evidence identifiers and business idempotency keys in every transition. Lobster retry does not create business idempotency automatically.

### Time and output bounds

OpenClaw's tool defaults are `timeoutMs: 20000` and `maxStdoutBytes: 512000` (`upstream_openclaw/extensions/lobster/src/lobster-tool.ts:273-290`). The runner applies an abort signal and creates byte-limited stdout/stderr sinks (`upstream_openclaw/extensions/lobster/src/lobster-runner.ts:167-179,275-315`). A workflow step can also define `timeout_ms`; Lobster validates it and kills a timed-out shell step (`upstream_lobster/src/workflows/file.ts:57-87,592-602,1261-1271`; the separate check at `:320-329` is for a `parallel` block's own timeout).

Do not interpret those defaults as permission to emit 512 KB per step. Version 3.0 should set explicit smaller bounds and require compact outputs. Source inspection found no OpenClaw integration test demonstrating that `maxStdoutBytes` constrains a workflow-file shell step's internally buffered result: Lobster's `runShellCommand` accumulates child stdout/stderr into strings before returning them (`upstream_lobster/src/workflows/file.ts:2764-2818`), whereas the OpenClaw cap wraps the runtime context streams. Until a real regression test proves the effective bound, every helper must enforce its own record/byte limit and the release gate must include an oversized-workflow test.

### Approval and resume

A successful approval pause returns `status: needs_approval` with a `resumeToken` and normally an eight-hex-character `approvalId`. Upstream resume uses exactly one of those plus `approve: true|false`; a denial returns `cancelled` and must never run the gated side effect (`upstream_openclaw/docs/tools/lobster.md:284-327`). Version 3.0 does not expose the upstream tool, bearer token, resume, cancel, or decision to an agent. Agent-facing `vcrun` redacts the bearer token and returns only the short approval ID; non-allowlisted `vcrun-control` resolves that ID from the owner-only state index after authenticating the operator path.

Continuation state is not contained in the token. Lobster persists the pipeline/workflow state as JSON under `LOBSTER_STATE_DIR`, defaulting to `~/.lobster/state` (`upstream_lobster/src/state/store.ts:6-20`; `upstream_lobster/src/pipeline_resume_state.ts:95-199`). Current Lobster writes new state atomically with mode `0600` and uses exclusive `0600` approval-index files (`upstream_lobster/src/state/store.ts:119-203,218-224,250-300`). Successful resume/cancel removes the used state and index; runtime errors retain it for retry (`upstream_lobster/src/core/tool_runtime.ts:195-243,247-330`).

The resume token is only base64url-encoded JSON and is not cryptographically signed (`upstream_lobster/src/token.ts:1-14`). Treat it as a bearer secret. The short approval ID is a local state-index correlation handle, not authentication, and still requires the authenticated operator wrapper:

- never log or publish the bearer token; redact it before producing agent-visible output;
- never accept a decision or bearer token from an agent or untrusted channel; the operator control path must authenticate the stable operator and expected internal review action independently;
- persist the Lobster state directory on local durable storage with owner-only access;
- expire and garbage-collect abandoned state operationally, because the Lobster token itself does not encode an enforced expiry in the inspected adapter;
- for any external action, use a Postgres one-time, scoped, expiring approval record as the hard authorization gate inside the exact consequential helper command. A Lobster pause alone is never sufficient external-action authorization.

Lobster v2026.6.11 contains optional workflow identity fields and environment inputs, but OpenClaw's tool interface exposes only `token`/`approvalId` and boolean `approve`; the normalized envelope also omits the identity metadata (`upstream_openclaw/extensions/lobster/src/lobster-tool.ts:240-263`; `lobster-runner.ts:181-209`). There is no per-channel-approver identity binding in this adapter. This is why the OpenClaw adapter is not used for resume and why Lobster approval remains control only. On the CLI path this package does use, Lobster checks an approver only when an approver requirement is present on the approval request — and, verified against the pinned runtime, that requirement can arrive by **three** routes, not just the workflow file: the step's own `required_approver`/`require_different_approver` declaration, the step's JSON output (`requiresApproval.requiredApprover`), or the process environment, which `extractApprovalRequest` reads as `LOBSTER_APPROVAL_REQUIRED_APPROVER`, `LOBSTER_APPROVAL_REQUIRE_DIFFERENT_APPROVER` and `LOBSTER_APPROVAL_INITIATED_BY` whenever the declaration is absent (`@clawdbot/lobster/dist/src/workflows/file.js:1555-1571` in the pinned image). None of the three is present here: the shipped `persist_approval` step declares neither field, emits no `requiresApproval` object, and `vcrun` builds a fixed minimal environment that sets none of those variables. The `LOBSTER_APPROVAL_APPROVED_BY` value `vcrun-control` passes on resume is therefore recorded as metadata and never verified by Lobster. Treat the environment route as part of this boundary: setting any of those three variables in `vcrun`'s environment would silently move approver enforcement into Lobster without a workflow-file change, which is a reviewed design change rather than tuning. Authorization remains entirely the wrapper's: an authenticated operator on the non-agent administrative path. `vcrun-control` must bind the internal review decision to an authenticated operator in the administrative audit. For any external action, Version 3.0 additionally requires Postgres-backed approver identity, exact action/target/scope, preview hash, expiry, and one-time consumption in `vcops`. Never claim that Lobster supplies those properties.

### Required state configuration

The gateway and any CLI/tool container that may run or resume Lobster must set:

```text
LOBSTER_STATE_DIR=/home/node/.openclaw/lobster/state
```

That path is inside the existing persistent `openclaw-state` volume. It must be included in backup/restore, must remain writable while the root filesystem is read-only, and must not be shared by different gateways or trust domains. The current Compose file now sets this variable for the gateway and CLI; live persistence and restore remain hard release gates.

## Task Flow operational contract

### Storage and lifecycle

Task Flow is the orchestration layer above background tasks. Managed flows are controlled by plugin/runtime code; detached ACP/subagent work may receive an automatically created one-task mirrored flow (`upstream_openclaw/docs/automation/taskflow.md:10-43`).

The exact flow statuses are:

| Status | Contract |
|---|---|
| `queued` | created but not progressing |
| `running` | controller is actively progressing |
| `waiting` | parked on structured wait metadata |
| `blocked` | no usable child result; blocked task/summary explains why |
| `succeeded` | controller marked the flow complete |
| `failed` | controller/runtime marked an error |
| `cancelled` | cancellation requested and active children settled |
| `lost` | authoritative backing state disappeared |

The source union is `upstream_openclaw/src/tasks/task-flow-registry.types.ts:14-37`; the public meanings are in `docs/automation/taskflow.md:45-56`.

Records live in `$OPENCLAW_STATE_DIR/state/openclaw.sqlite`, table `flow_runs`, alongside task records. The path resolver is `upstream_openclaw/src/state/openclaw-state-db.paths.ts:14-40`; SQLite row mapping is `src/tasks/task-flow-registry.store.sqlite.ts:23-113`. This is local OpenClaw operational state and must remain on a local durable filesystem.

### Revision discipline

Each flow mutation is optimistic-concurrency controlled:

1. read the current flow;
2. pass its exact `revision` as `expectedRevision`;
3. on success, carry forward the returned flow's new revision;
4. on `revision_conflict`, re-read and decide whether the intended transition is still valid; never blind-retry a stale mutation;
5. record the conflict in operational telemetry.

The registry rejects a stale revision and returns the current record (`upstream_openclaw/src/tasks/task-flow-registry.ts:502-533`). Waiting, resume, finish, fail, and cancel-intent mutations all require `expectedRevision` (`task-flow-registry.ts:536-655`).

### Cancellation

Cancellation is sticky. `openclaw tasks flow cancel <lookup>` records cancel intent, cancels active linked children, refuses new managed child tasks, and finalizes `cancelled` when none remain. The persisted intent survives a gateway restart; maintenance can finish a cancellation that was waiting for children (`upstream_openclaw/docs/automation/taskflow.md:62-85`; `src/tasks/task-flow-registry.maintenance.ts:53-90,151-176`).

Never implement cancellation by deleting a flow row or by only changing Postgres. A business workflow cancellation and an OpenClaw flow cancellation are separate, correlated state transitions; both must be idempotent and auditable.

### Managed Lobster mode caveat

OpenClaw can create a managed flow when a Lobster run includes `flowControllerId` and `flowGoal`, and resume it with `flowId` plus `flowExpectedRevision`. Approval maps to `waiting`, success/error to terminal mutations (`upstream_openclaw/docs/tools/lobster.md:298-307`; `extensions/lobster/src/lobster-taskflow.ts:109-158,164-288`).

Version 3.0 **does not use managed Lobster/Task Flow mode**. The inspected adapter calls `taskFlow.finish` for every `ok: true` envelope other than `needs_approval`; that includes Lobster's `status: cancelled` (`upstream_openclaw/extensions/lobster/src/lobster-taskflow.ts:138-157`). The upstream tests cover success, waiting, error, and revision conflict but do not cover a denied/cancelled managed resume (`lobster-taskflow.test.ts:61-227`). Therefore a managed flow can report `succeeded` after a denied Lobster approval. The adapter also lacks the hard approver-identity binding required by this system. Managed mode remains prohibited until upstream changes or a separately maintained, source-audited guard both map denial to cancellation correctly and bind approval to the authorized identity and scope. Postgres business workflow state remains authoritative meanwhile.

## Inspection, maintenance, recovery, and backup

Use supported CLI surfaces; do not mutate `openclaw.sqlite` manually. `openclaw`
is not installed on the deployment host — it lives in the gateway image — so
every bare `openclaw …` line below runs through the gateway container in the
form `docker compose -f docker-compose.yml -p openclaw-lead-research-v3
--env-file .env exec openclaw-gateway openclaw …`, exactly as `docs/RUNBOOK.md`
§5.3 states.

```bash
# Inspect tasks and flows
openclaw tasks flow list --json
openclaw tasks flow show <flow-id-or-owner-key> --json

# Audit inconsistencies
openclaw tasks audit --json
openclaw tasks audit --severity error --json

# Preview first; apply only after a verified backup
openclaw tasks maintenance --json
openclaw tasks maintenance --apply --json

# Request durable cancellation
openclaw tasks flow cancel <flow-id-or-owner-key>

# Create and verify an upstream-consistent state backup
openclaw backup create --output <backup-directory> --verify
openclaw backup verify <archive.tar.gz> --json
```

`tasks audit` includes Task Flow findings such as `restore_failed`, `stale_waiting`, `stale_blocked`, `cancel_stuck`, `missing_linked_tasks`, and `blocked_task_missing`. `tasks maintenance` previews or applies reconciliation and pruning (`upstream_openclaw/docs/cli/tasks.md:75-123`). Terminal flows are pruned after seven days when they have no active linked tasks (`src/tasks/task-flow-registry.maintenance.ts:17-50`).

`openclaw doctor` imports older `flows/registry.sqlite` and `tasks/runs.sqlite` sidecars into the shared database (`upstream_openclaw/docs/automation/tasks.md:306-320`). Run it as an upgrade/migration operation, retain its output, then run the audit commands again.

The upstream backup command snapshots SQLite safely with `VACUUM INTO` and intentionally skips WAL/SHM and other volatile files (`upstream_openclaw/docs/cli/backup.md:31-48`). The package recovery point instead takes an exclusive lifecycle lock and stops gateway and CLI before archiving `/home/node/.openclaw`, so Task Flow SQLite, inbound-media state, and Lobster continuation files are quiesced. While consumers remain stopped it also captures Postgres (including verified principals and bounded preferences), the read-only operator inbox, and the named quarantine volume; validates database local-artifact URIs and hashes against the staged archives; excludes generated runtime configuration and exec approvals; writes to a new private partial directory; and publishes with one rename only after all checks pass. This establishes a structurally consistent package recovery point, but only the disposable-target checks below can establish live recoverability.

OpenClaw v2026.7.1 provides `backup create` and `backup verify`, but no `openclaw backup restore` command (`upstream_openclaw/src/cli/program/register.backup.ts:11-93`). The package's restore script is custom. It must be tested on a disposable deployment with these hard checks:

1. archive hash verification succeeds before destructive changes;
2. gateway and every CLI/state consumer are stopped before state replacement;
3. Postgres, OpenClaw state (including `openclaw.sqlite`, inbound media, and Lobster state), read-only operator inbox originals, and named-volume quarantine are restored as one named recovery point, with every database local-artifact URI and SHA-256 reconciled;
4. file ownership and `0600`/`0700` secret-state permissions are correct;
5. gateway readiness and `openclaw doctor` succeed;
6. `tasks audit --severity error --json` returns no errors;
7. a pre-backup waiting Lobster approval can resume exactly once after restore;
8. a pre-backup Task Flow is visible with the same flow id/revision and rejects a stale expected revision;
9. an intentionally cancelled flow stays cancelled;
10. application Postgres correlation records still refer to the restored operational ids.

## Hard passing gate

G5 passes only when every row has retained machine-readable evidence from the packaged image and configuration.

| Evaluation | Hard pass condition |
|---|---|
| Exact versions | Running host reports OpenClaw `2026.7.1`; installed Lobster package resolves to `2026.6.11`; image digest is recorded |
| Direct tool exposure | Effective tool inventory proves `lobster` is unavailable to `vc-chief`, `data-steward`, every specialist, and every sandboxed or non-sandboxed agent context |
| Fixed dispatcher | Only `data-steward` can execute exact-path `vcrun`; negative tests reject paths, pipelines, shell text, unknown workflows/args, collisions, traversal, environment/cwd/limit overrides, tokens/decisions, resume/cancel, and trailing arguments |
| Operator separation | `vcrun-control` and `vcops-operator` are absent from every agent tool/exec policy; only the authenticated administrative path can run them; spoofed caller environment cannot select operator mode or identity |
| Workflow inventory | Every accepted ID resolves to one immutable reviewed file; release checksums match; static validation proves steps invoke only the exact immutable `vcops` path and approved authoring subset |
| State persistence | `LOBSTER_STATE_DIR` is writable, on a local durable volume, and included in backup/restore |
| Argument injection | quotes, `$`, backticks, newlines, command substitution, normalized-name collision, and unknown keys cannot change the executed command |
| Step references | fully qualified `$step.json.<field>` refs (and `$step.approved`) transfer schema-valid JSON; bare `$step.json`/`$step.stdout`, unknown/out-of-order step ids and unlisted paths are rejected by `validate_workflows.py`; a missing required ref fails closed at the receiving `vcops` command, not in Lobster, which resolves it to an empty value |
| Timeout | a hung command is terminated within the configured bound and records a failed business/operational outcome |
| Output limit | an oversized workflow-file command is stopped or rejected within a measured memory/output bound; the gateway remains ready |
| Internal review pause | run returns `needs_approval`; the Lobster pause is labelled internal control-only; no evaluation persistence occurs before the authenticated operator decision |
| Operator resume | agent attempts to resume/cancel or supply a token fail; authenticated `vcrun-control` approve/deny/cancel applies once, records non-secret operator audit, never logs the token, and repeat/wrong/expired state fails without re-running completed steps |
| External authorization | no current Lobster pause grants external-effect authority; any future external-effect command atomically consumes Postgres identity/scope/action/target/preview-hash/expiry binding, and wrong/replayed/expired authorization fails without external side effect |
| Restart resume | waiting approval survives gateway restart without re-running completed steps |
| Task Flow revisions | stale mutation returns `revision_conflict`; controller re-reads before any further mutation |
| Cancellation | active child cancellation is requested, new child creation is refused, final status becomes and remains `cancelled` |
| Managed-mode semantics | config and invocation evidence prove managed Lobster/Task Flow fields are never exposed or passed; denied Lobster state cannot mark an OpenClaw flow succeeded because no managed flow is created |
| Audit/maintenance | audit reports no error findings; maintenance preview is reviewed before `--apply`; post-apply audit is clean |
| Recovery | fresh disposable restore passes all ten recovery checks above |

Missing Docker, gateway, model, channel credentials, or a disposable restore target is a blocked live gate, not a pass. Source inspection and mocked upstream unit tests cannot substitute for these deployment evaluations.
