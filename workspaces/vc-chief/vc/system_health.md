# System Health

Policy version: `3.0`

Health is evidence-backed. `/healthz` is process liveness; `/readyz` plus Postgres and configured channel/plugin dependencies is readiness.

## Hard blockers

- Postgres unavailable or authoritative queries fail;
- reviewed customization profile, resolver, config, canonical schemas, and
  filesystem inventories do not match exactly (the shipped sample is 12 agents
  and 26 skills, but the validator derives configured counts);
- missing/zero/failed mandatory fixture suite;
- unconsumed approval scope/expiry/replay invariant failure;
- business runs stuck `started` after terminal/cancelled/lost Task Flow state;
- notification marked delivered without provider acknowledgement;
- high/blocking identity or approval contradiction;
- document intake path/MIME/limit safety failure;
- failed migration or rollback evidence.

## Warnings

Active lead stale 14 days; high-priority action stale 3 business days; pending extraction 24 hours; blocking contradiction 2 business days; held notification one hour past `deliver_after`; failed/lost flow 24 hours; stale policy/report snapshot.

The report records checked authority, query/report timestamps, counts and IDs, not only booleans. Missing dependent evidence is unknown/failure, never healthy. Checks do not repair state; remediation is a separate approved/deterministic operation.
