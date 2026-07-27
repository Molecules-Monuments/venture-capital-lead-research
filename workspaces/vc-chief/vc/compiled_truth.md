# Compiled Truth Policy

Policy version: `3.0`

Compiled truth is a cited snapshot over Postgres evidence, not an independent source and not OpenClaw model memory.

Every snapshot contains:

1. current view;
2. coverage by thesis area;
3. dated evidence timeline;
4. contradictions, superseded/stale facts, and ordinary changes;
5. missing-data states;
6. source/fact/artifact appendix;
7. prior snapshot and material delta;
8. snapshot time and policy version.

The persisted evidence hash covers the complete frozen fact/source ledger,
contradiction ledger, trajectory ledger, and database-derived decision guards.
Removing a contradicted fact from current view never removes its history or its
open finding. `identity_reliable` is false for an active identity conflict;
`blocking_contradiction` is true for any active blocking contradiction. Old
snapshots without a complete guard state cannot support a new final evaluation.

Only evidence with resolvable provenance may support a material sentence. Keep `submitted_claim`, `verified_fact`, `derived_inference`, `contradicted`, `stale`, `retracted`, and `unknown` distinct. Claimed-only coverage is not verified coverage. Prefer a newer reliable observation in the current view while retaining history; route comparable movement to trajectory and incompatible overlapping assertions to contradiction.

A stale or incomplete snapshot cannot support final scoring or memo. Final
evaluation reuses these database guards and overrides contrary caller
booleans; it also rejects the snapshot as stale if live same-lead guard IDs
changed after compilation. The caller is never the authority for identity or
blocking-conflict state. Snapshot persistence is versioned and occurs only inside the fixed
`evaluate-lead` workflow or through the non-allowlisted operator helper.
