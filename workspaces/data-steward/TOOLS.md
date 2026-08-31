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

The only executable paths are `/workspaces/vc-chief/vc/bin/agent/vcops` and `/workspaces/vc-chief/vc/bin/agent/vcrun`, invoked directly with reviewed subcommands and literal validated arguments. Both live under the `bin/agent/` prefix: that directory holds exactly the two environment-scrubbed launchers a model lane may execute, which is what keeps the operator-only siblings in `bin/` (`vcops-operator`, `vcops-workflow`, `vcrun-control`) unreachable from an allowlist entry. The outer exec timeout is 420 seconds so a 360-second fixed runner plus bounded cleanup is not cut off by the tool. `vcrun` selects a reviewed fixed workflow ID; it accepts no workflow path, pipeline, resume token, environment, cwd, command, timeout, or output override. No shell/interpreter, SQL client, alternate path, pipe, redirect, expansion, inline evaluation, command chaining, or executable modification is allowed. `config/exec-approvals.json` is the authority for these paths. At container start the initializer loads the read-only image-baked seed at `/opt/openclaw-seed/exec-approvals.json` into the `exec_approvals_config` row of the OpenClaw state database and asserts its reviewed keys — version, defaults, the single `data-steward` agent entry, and the exact two-entry allowlist — by reading that row back; it is deliberately not a byte comparison, because the harness stores its own socket token in the same row. There is no longer a writable JSON copy in the state volume, and the initializer asserts that none is left there: a leftover `exec-approvals.json` makes every approvals read and write throw rather than fall back. Host-side, `tests/infrastructure` pins the same two entries and `validate_skill_system.py` cross-checks every agent-reachable helper against them. Do not hand-edit it to match this document. Verify state through Postgres. Sandbox mode is off and is not a process or tenant boundary.

Agent-mode `vcops` exposes only read-only preflight, health, lookup, preview,
and evaluation-preview commands. Every mutating helper command is rejected.
Reviewed mutations occur only inside the eighteen fixed `vcrun` workflows through
the non-allowlisted, environment-scrubbed `vcops-workflow` child launcher.
Approval decisions, bearer-token operations, notification delivery receipts,
and workflow continuation require separate non-allowlisted operator paths;
never attempt to invoke or simulate them.
