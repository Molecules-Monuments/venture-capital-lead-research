# VC Chief Tool Contract

## Allowed tool IDs

- `sessions_spawn`
- `sessions_yield`
- `agents_list`
- `sessions_list`
- `sessions_history`
- `session_status`
- `read`
- `skill_workshop`

## Denied tool IDs

- `exec`
- `lobster`
- `gateway`
- `cron`
- `nodes`
- `sessions_send`
- `memory_search`
- `memory_get`
- `apply_patch`
- `write`
- `edit`

## Use constraints

Read only governance and active-task inputs in this workspace. Conversational Markdown memory and automatic compaction memory writes are disabled by default because this release has no reviewed peer-scoped persistence lane. Postgres entity resolution is the only authoritative memory mechanism. Spawn only an allowed specialist after creating the canonical pre-spawn evaluation and only for a dependency-ready task; use yield rather than polling. Direct Lobster is denied because it can spawn arbitrary shell commands. A reviewed fixed workflow may be requested only through a bounded `data-steward` assignment to the immutable `vcrun` launcher. `skill_workshop` is limited by the trusted runtime hook to create/update/revise/list/inspect pending proposals; apply/reject/quarantine and unknown actions fail closed. Sandbox mode is off and is not process or tenant isolation.
