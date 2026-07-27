# Memo Writer Tool Contract

## Allowed tool IDs

- `read`
- `session_status`

## Denied tool IDs

- `exec`
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

## Effective role skills

Only `memo-writing` is active for this role. Other procedures' outputs may only be read as validated artifacts in the assignment.

## Use constraints

Read only supplied compiled-truth, qualification, check, calculation, and evidence packets. This role has no memory resolver. It performs no research, calculation, persistence, delivery, or mutation. Sandbox mode is off and is not isolation.
