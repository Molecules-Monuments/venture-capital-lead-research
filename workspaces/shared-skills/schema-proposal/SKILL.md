---
name: schema-proposal
description: Produce a minimal reviewable schema or governance proposal without applying it.
---

# Schema Proposal

## Inputs

- Repeated gap evidence, affected records/workflows, proposed change, compatibility/version impact, migration preview, rollback, and risk.

## Contract

First test whether existing typed columns, JSON metadata, or policy structure safely represent the need. If not, propose the smallest additive change with constraints, indexes, backfill, validation, rollback, ownership, and approval scope. Never apply migrations or mutate governance.

## Evidence and failures

Cite repeated examples and affected query/workflow paths. Unsupported need, destructive-only migration, absent rollback, privacy expansion, or ambiguous owner is blocked.

## Output

Return `title`, `problem_evidence`, `change`, `migration_preview`, `backfill`, `validation`, `rollback`, `risk`, `approval_required`, and `persistence_request`. Route proposal record requests to `data-steward`; direct agent-mode mutation is forbidden and unsupported records require the operator helper. No migration, external write, or channel send.

## Persistence (Version 3.0)

A proposal is captured durably for operator review through the fixed `proposal-record` workflow (via `data-steward`); it is recorded, never applied. Applying a schema/source/skill change remains a reviewed operator repository action.
