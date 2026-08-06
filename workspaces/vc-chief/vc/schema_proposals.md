# Schema Proposal Policy

Policy version: `3.0`; proposals never apply migrations. Durable proposal records go through the reviewed fixed workflow `proposal-record` (routed via `data-steward` and `vcrun`); decisions are operator-lane only via `proposal-decide`.

## Purpose

This file governs changes to tables, columns, enums, scoring fields, indexes, views, and required governance headings.

Agents may propose schema changes. Agents may not apply schema changes without explicit human approval.

## When to Propose

Create a schema proposal when:

- A missing field appears repeatedly across leads.
- A client requires a new taxonomy or scoring dimension.
- A JSONB metadata field has become stable and operationally important.
- A resolver route needs a new durable state object.
- A governance document requires a required heading that lint should enforce.
- Existing enum values no longer represent real production states.

Do not propose a schema change when:

- The need is one-off.
- The data is sensitive and should remain in documents or object storage.
- The value can live safely in `metadata` until it proves stable.
- The change only improves naming preference without operational impact.

## Proposal Template

Each proposal must include:

- title
- proposal type
- requester
- owning agent
- problem statement
- proposed change as structured JSON
- affected files
- affected tables
- migration preview
- rollback plan
- risk level
- approval requirement

## Approval Rules

| Risk | Examples | Approval |
|---|---|---|
| `low` | New optional markdown heading, new report view | Data owner approval |
| `medium` | New nullable column, new index, new enum value | Data owner plus system owner |
| `high` | Backfill, data migration, scoring logic change | Partner or client sponsor approval |
| `blocking` | Destructive migration or confidential data movement | Explicit written approval and backup verification |

## Migration Preview Standard

Migration previews must show:

- SQL or pseudocode.
- Expected rows affected.
- Whether downtime is expected.
- Whether data backfill is required.
- Rollback SQL or rollback procedure.
- Test plan.

## Plain Vanilla Example

Title: Add lead urgency reason

Proposal type: `schema_change`. Requester: `partner-1`. Owning agent:
`data-steward`.

Problem:

Partners often ask why a lead is high priority. The current `priority` field captures level but not the reason.

Proposed change:

```json
{
  "operation": "add_column",
  "table": "leads",
  "column": "urgency_reason",
  "type": "TEXT",
  "nullable": true,
  "constraint": "CHECK (urgency_reason IS NULL OR btrim(urgency_reason) <> '')",
  "backfill": null
}
```

Affected files: the new numbered migration, `docs/DATA_MODEL.md`,
`docs/SCHEMA.sql` (regenerated), `manifest.json` (re-pinned).
Affected tables: `leads`.

Migration preview:

```sql
ALTER TABLE leads ADD COLUMN urgency_reason TEXT
  CHECK (urgency_reason IS NULL OR btrim(urgency_reason) <> '');
```

No new GRANT: `002_runtime_grants.sql` already grants `openclaw_runtime`
table-level `SELECT, INSERT, UPDATE` on `leads`, and this package grants by
table rather than by column, so a new column inherits it. A proposal that adds a
*table* would need its own grant in the same migration.

Expected rows affected: 0 — the column is nullable and nothing is backfilled.
No downtime; no backfill required.

Rollback plan: a further forward migration dropping the column. Applied
migrations are never edited or reverted in place, so the rollback is itself a
new numbered file.

Risk level: `medium` — a new nullable column, per the approval table above, so
it needs data owner plus system owner.

Approval requirement: recorded through `proposal-record`, decided on the
operator lane with `proposal-decide`. Acceptance authorizes an operator release,
not a runtime change: no agent lane applies a migration.
