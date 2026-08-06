# Active Sourcing

> [MUST_CUSTOMIZE] Define thesis concepts, public sources, negative terms,
> novelty/duplicate review, source budget, and stop rules from local yield data.

Policy version: `3.0`; source/thesis content retained from the 2026-06-10 ground source and subordinate to Version 3 trust, entity-resolution, budget, approval, and persistence rules.

## Definition

Active sourcing is thesis-directed search performed by the system or operator.

## Allowed active sourcing

- Search public websites for companies matching thesis categories.
- Search public event/demo-day lists.
- Search public portfolio pages.
- Query approved third-party connectors within rate and cost limits.
- Generate a target list for human review.

## Active sourcing workflow

1. Read `thesis.md`.
2. Read `exclusion_criteria.md`.
3. Select one source class.
4. Collect candidates with source URLs.
5. Deduplicate by canonical domain.
6. Persist through the fixed `outbound-scout` workflow. It stamps
   `origin_group=outbound`, `origin_subtype=active_sourcing` — the
   intake-mechanism subtype, which is not a workflow argument and cannot be
   overridden. Record `source_based` or `event_based` as the *model*
   classification inside the scout packet, not as the persisted subtype; see
   `lead_origin_taxonomy.md` for why both layers exist.
7. Run pre-qualification before deeper research.

## Approval gates

Active sourcing must not contact founders, request demos, join private groups, bypass login/paywall restrictions, or create accounts without approval.

## Registering watched sources

A source the fund wants surveilled on a cadence is registered in the runtime
watchlist via the `source-watch` fixed workflow (see `passive_sourcing.md`),
which the `source-scan` workflow then screens by cadence. Removing a source uses
`source-unwatch`.
