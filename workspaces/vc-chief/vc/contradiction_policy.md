# Contradiction Policy

Policy version: `3.0`

## Definition

A contradiction is two assertions about the same entity and normalized fact definition whose validity periods overlap and which cannot both be true.

Not contradictions:

- two non-overlapping dated observations showing ordinary change;
- a stale old value superseded by a newer observation;
- different currencies, units, periods, cohorts, gross/net definitions, or accounting bases before normalization;
- one-point versus multi-point trajectory;
- absence of evidence.

## Finding kinds

`contradiction`, `ordinary_change`, `superseded`, `stale`, `not_comparable`, `identity_conflict`.

Severity is `low`, `medium`, `high`, or `blocking`. Identity, approval, legal status, outreach eligibility, and materially incompatible commercial evidence may be blocking.

## Required evidence

Every finding cites both fact/source IDs, entity key, metric definition, unit/currency, period/cohort, validity interval, source date, and normalization. Preserve both records. Resolution requires stronger evidence or human acceptance of risk; it never deletes history.

Ordinary changes route to trajectory analysis. Unresolved high/blocking contradictions are visible in compiled truth and memos and prevent `high_priority` unless a human reviews them.
