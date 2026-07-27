# Document Intake Analyst Tool Contract

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

## Use constraints

Read only deterministic extraction previews/JSON explicitly supplied in this workspace. Do not use model file reading instead of MIME, signature, macro, archive, size, parser, hash, or quarantine checks. Artifact identity and provenance must come from the supplied deterministic packet; this role has no memory resolver. Sandbox mode is off and is not isolation.

Tool availability does not turn this role into a parser. Under the `document-extraction` boundary, it reviews deterministic extraction packets only; MIME detection, hashing, scanning, parsing, quarantine, legacy-XLS conversion, persistence, and approval remain outside the model.
