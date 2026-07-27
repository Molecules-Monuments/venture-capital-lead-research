---
name: compiled-truth
description: Build a cited current view and dated timeline from authoritative lead evidence without creating new facts.
---

# Compiled Truth

## Inputs

- Lead/company identifiers and a supplied compiled-truth policy packet.
- Postgres evidence export containing typed facts, fact sources, document facts, events, relationships, signals, artifacts, and prior evaluations.

## Contract

Postgres is authoritative. Include only evidence whose provenance can be resolved. Keep `submitted_claim`, `verified_fact`, `derived_inference`, `contradicted`, `stale`, `retracted`, and `unknown` distinct. Weak or claimed evidence may describe coverage but never becomes verified coverage. Prefer a newer reliable observation in the current view while retaining every superseded observation in the timeline.

## Evidence and failures

Every material sentence cites source/fact/artifact IDs and observation dates. A missing source, unresolved identity conflict, or blocking contradiction lowers confidence and is surfaced, never silently resolved. Fail closed when the evidence export is incomplete or stale for the decision requested.

## Output

Return `current_view`, `coverage_by_thesis_area`, `timeline`, `contradictions`, `stale_fact_ids`, `missing_data`, `source_ids`, `confidence`, and `persistence_request`. Do not persist directly; route the snapshot through `data-steward` and the fixed `evaluate-lead` workflow. No external writes or channel sends.
