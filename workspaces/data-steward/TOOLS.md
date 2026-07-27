# Data Steward Tool Contract

## Allowed tool IDs

- `exec`
- `read`
- `session_status`

## Denied tool IDs

- `web_search`
- `web_fetch`
- `gateway`
- `cron`
- `nodes`
- `sessions_spawn`
- `sessions_send`
- `memory_search`
- `memory_get`
- `write`
- `edit`
- `apply_patch`
- `skill_workshop`

## Use constraints

The only executable paths are `/workspaces/vc-chief/vc/bin/vcops` and `/workspaces/vc-chief/vc/bin/vcrun`, invoked directly with reviewed subcommands and literal validated arguments. The outer exec timeout is 420 seconds so a 360-second fixed runner plus bounded cleanup is not cut off by the tool. `vcrun` selects a reviewed fixed workflow ID; it accepts no workflow path, pipeline, resume token, environment, cwd, command, timeout, or output override. No shell/interpreter, SQL client, alternate path, pipe, redirect, expansion, inline evaluation, command chaining, or executable modification is allowed. The host approvals file must match these exact immutable paths and must not include `vcops-operator` or `vcrun-control`. Verify state through Postgres. Sandbox mode is off and is not a process or tenant boundary.

Agent-mode `vcops` exposes only read-only preflight, health, lookup, preview,
and evaluation-preview commands. Every mutating helper command is rejected.
Reviewed mutations occur only inside the eighteen fixed `vcrun` workflows through
the non-allowlisted, environment-scrubbed `vcops-workflow` child launcher.
Approval decisions, bearer-token operations, notification delivery receipts,
and workflow continuation require separate non-allowlisted operator paths;
never attempt to invoke or simulate them.
