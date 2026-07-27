---
name: eval-fixture-check
description: Execute deterministic routing, scoring, memo, approval, and lifecycle fixtures and fail when fixtures are absent or behavior is wrong.
---

# Eval Fixture Check

## Inputs

- Explicit fixture paths/content, expected schemas/outcomes, target version, and supplied evaluation policy.

## Contract

Parse every JSONL line, require non-empty fixtures for every configured suite, execute the real deterministic entry point, and compare semantic outputs—not only keys. Cover routing inventory, score boundaries, missing-data behavior, contradictions versus change, approval replay/expiry/scope, document limits, lifecycle rollback, and notification delivery state.

## Evidence and failures

An absent, skipped, malformed, or zero-case suite is a hard failure. Capture command/version, per-case expected/actual result, duration, and stderr without secrets.

## Output

Return `ok`, `suite_counts`, `passed`, `failed`, `skipped`, `failures`, `target_version`, and `report_request`. Route report requests to `data-steward`; direct agent-mode mutation is forbidden. No external write or channel send.

## Reachability (Version 3.0)

The authoritative deterministic check here runs as operator/CI tooling (`scripts/validate_skill_system.py` / `verify_offline.py`), not as a chief runtime action — the chief has no `exec`. As a chief agent-skill this is a review/advisory lens that requests or summarizes the check; the enforcing gate is the release pipeline.
