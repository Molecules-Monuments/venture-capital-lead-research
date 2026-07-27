# Knowledge Model

Policy version: `3.0`

Postgres is the canonical knowledge store.

## Records

- canonical entities and aliases;
- companies and leads;
- immutable artifacts plus lead-artifact joins;
- document facts with page/sheet/cell provenance;
- typed facts and fact-source joins;
- events and temporal relationships;
- evaluations, compiled-truth snapshots, and memos;
- merge proposals;
- approvals, notification outbox/attempts, and business workflow audit.

Every material fact has entity, fact type, typed value plus original representation, unit/currency/period/cohort where applicable, evidence status, confidence, observed/source/valid time, source IDs, actor/run IDs, and version. Updates append/supersede; they do not erase history.

Canonical creation follows memory lookup. Exact domain/hash/stable source IDs precede aliases and fuzzy candidates. Merge proposals require approval and preserve redirect/audit history. Artifact content hashes are globally reusable; lead relationships are many-to-many.

OpenClaw workspace memory and Task Flow/Lobster state never replace these records.
