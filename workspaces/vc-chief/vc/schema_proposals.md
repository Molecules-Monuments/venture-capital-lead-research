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

Problem:

Partners often ask why a lead is high priority. The current `priority` field captures level but not the reason.

Proposed change:
