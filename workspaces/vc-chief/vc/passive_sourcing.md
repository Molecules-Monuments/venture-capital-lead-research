# Passive Sourcing

> [MUST_CUSTOMIZE] Define reviewed watch sources, cadence, owner, permitted data,
> rate/terms, expected signal, and disable/rollback rule.

Policy version: `3.0`; source content retained from the 2026-06-10 ground source and governed by Version 3 trust, budget, and persistence rules.

## Definition

Passive sourcing monitors configured sources and external signals without direct engagement.

## Passive signal types

- Product launches.
- Funding announcements.
- Public customer stories.
- Hiring spikes.
- Open-source activity.
- Technical blog posts.
- Conference agenda appearances.
- Regulatory or market events.

## Workflow

1. Read `primary_sources.md`.
2. Check only enabled sources.
3. Capture source URL, retrieved time, and as-of date.
4. Create candidate leads only when the signal maps to the thesis.
5. Store low-confidence signals without over-scoring them.

## Noise controls

- Ignore generic AI announcements without product specificity.
- Ignore stale links unless relevant to current traction.
- Prefer direct source pages over reposts.

## Runtime (Version 3.0)

The watchlist is a database registry, not just this document. Manage and run it
through the fixed workflows via `data-steward`:

- `source-watch` — register one watched source (name, URL, class, cadence), or
  refresh the descriptive fields of an already-enabled one. This is how
  "monitor this website" is applied. This lane cannot re-enable a **disabled**
  entry — not even one it disabled itself through `source-unwatch`; that fails
  with `source_watch_disabled` and must be escalated to the operator lane
  (`vcops-operator source-watch`).
- `source-unwatch` — disable a watched source without deleting its history.
- `source-scan` — atomically claim the enabled sources **due this cycle** (by
  cadence) and return the worklist. The scan lane never browses; for each due
  source the chief dispatches a read-only research specialist
  (`web_search`/`web_fetch`), and any thesis-matching candidate is persisted as
  low-authority evidence through the existing `outbound-scout` (candidate lead)
  and `evidence-record` (submitted claims) workflows for human review.

`source-scan` can be triggered on demand by the operator or on a reviewed
schedule once the OpenClaw `cron` job is deliberately enabled (see
`CUSTOMIZATION.md`). Autonomous outreach remains prohibited.
