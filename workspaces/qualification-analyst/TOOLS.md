# Qualification Analyst Tool Contract

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

Only `evidence-scoring` is active for this role. This role may read supplied check and deterministic-calculation artifacts but must not run, recreate, or alter them.

## Use constraints

Read only supplied compiled-truth, check, rubric, and calculation packets. This role has no memory resolver. It performs no research, calculation, persistence, notification, or mutation. Sandbox mode is off and is not isolation.
