# Lead Router Tool Contract

## Allowed tool IDs

- `read`
- `session_status`

## Denied tool IDs

- `exec`
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

Read only assigned workspace inputs. Consume the authoritative resolver packet supplied by the chief; this role has no memory resolver. Use session status only for the current task. The explicit allowlist is exhaustive even when a capability is not repeated in the deny list. Sandbox mode is off and is not process isolation.

Tool availability does not expand the role's skill inventory: use these tools only for `lead-routing`. Entity resolution, trust classification, approval, persistence, and specialist work remain supplied or downstream responsibilities.
