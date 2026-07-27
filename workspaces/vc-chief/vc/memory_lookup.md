# Authoritative Entity Resolution and State Retrieval

Policy version: `3.0` / resolver `entity-resolution.v1`

## Authorities

- Postgres is authoritative for companies, leads, aliases, artifacts, document facts, facts/sources, events, relationships, evaluations, memos, approvals, notifications, and business workflow audit.
- Task Flow SQLite (`$OPENCLAW_STATE_DIR/state/openclaw.sqlite`, including `flow_runs`) is authoritative only for orchestration status, revisions, cancellation, and recovery.
- Conversational Markdown memory/search is disabled in Version 3 because the
  package has no reviewed peer-scoped write and retrieval lane. Do not enable
  it as a substitute for Postgres entity or evidence retrieval.
- Lobster resume state is step-resume state only, never business authority.

## Required lookup

Before canonical creation, external research, connector use, scoring, memo
writing, or merge proposal, use typed `entity-resolve` in this order: exact
company/lead ID, domain, artifact hash, external ID, or channel identity;
normalized aliases; bounded fuzzy candidates. Then retrieve current verified
facts with source provenance and bounded evaluation/memo/workflow metadata.
Fuzzy results are candidates, never automatic matches.

One collision-free exact match links to the canonical record. Conflicting exact
identifiers, a hidden match above the confidentiality ceiling, a fuzzy
candidate, or a name match with an unseen domain blocks canonical creation
pending review. Prior memos cite facts but are not evidence themselves. A
database outage blocks authoritative lookup and creation; model context may not
substitute.

Return normalized typed identity, match method/confidence, authoritative IDs,
current facts plus provenance, bounded operational history, duplicate/review
candidates, and deterministic external-research allowance plus reason. The
read-only command persists nothing. Canonical creation is permitted only
through workflow-only `company-resolve-create`, bound to a preclaimed
`workflow_request`; the decision and its consumption are append-only.

`memory-lookup` remains only as a literal compatibility adapter. New workflows
and agents must not call it.
