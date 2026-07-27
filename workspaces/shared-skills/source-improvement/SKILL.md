---
name: source-improvement
description: Evaluate source yield and propose bounded sourcing-policy changes for human review.
---

# Source Improvement

## Inputs

- Versioned source list, observation window, sourced leads, quality outcomes, cost/rate/terms data, and supplied thesis/source policy.

## Contract

Compare sources on deduplicated candidates, qualified yield, evidence quality, cost, freshness, and false-positive burden. Separate correlation from causation and account for small samples. Propose additions/removals/cadence changes; paid, login-gated, sensitive, or material cadence changes require approval.

## Evidence and failures

Cite window, sample size, lead IDs, and calculations. Sparse data, attribution ambiguity, changed source terms, or missing cost data lowers confidence and blocks automatic removal.

## Output

Return `metrics`, `proposals`, `expected_effect`, `risks`, `approval_required`, and `persistence_request`. Never alter source lists, buy access, write externally, or send channels; route record requests to `data-steward`, with no direct agent-mode mutation.

## Persistence (Version 3.0)

A proposal is captured durably for operator review through the fixed `proposal-record` workflow (via `data-steward`); it is recorded, never applied. Applying a schema/source/skill change remains a reviewed operator repository action.
