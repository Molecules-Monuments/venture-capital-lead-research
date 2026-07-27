---
name: contradiction-check
description: Distinguish mutually incompatible claims from ordinary dated change, staleness, and definition mismatch.
---

# Contradiction Check

## Inputs

- Lead/company identifiers, supplied contradiction policy, and comparable typed facts with units, periods, definitions, provenance, and dates.

## Contract

A contradiction exists only when two claims apply to the same entity, metric definition, unit, and overlapping validity period and cannot both be true. Non-overlapping observations are ordinary change and belong in trajectory analysis. Unit, currency, period, cohort, gross/net, or identity mismatch is `not_comparable` until normalized. Staleness is not contradiction. Preserve both sides; never select a winner without stronger evidence.

## Evidence and failures

Cite both fact/source IDs, comparison keys, validity periods, and normalization performed. Invalid numeric parsing, absent units/dates, or identity ambiguity yields `not_comparable` or `needs_human_review`, never a fabricated contradiction.

## Output

Return `status`, `findings[]` with `kind`, `severity`, `blocking`, `left_fact_id`, `right_fact_id`, `reason`, plus counts and `persistence_request`. Route persistence requests to `data-steward`; direct agent-mode mutation is forbidden. No deletion, external write, or channel send.
