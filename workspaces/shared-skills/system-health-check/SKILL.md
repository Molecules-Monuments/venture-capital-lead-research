---
name: system-health-check
description: Evaluate business-state integrity, workflow completion, approvals, notifications, artifacts, and governance dependencies.
---

# System Health Check

## Inputs

- Deterministic Postgres health query output, Task Flow status export, OpenClaw readiness, and resolver/lint/fixture/security reports with timestamps.

## Contract

Postgres owns lead/evidence/approval/notification/workflow business state. Task Flow SQLite owns orchestration status only; free-form and Markdown memory are disabled. Check stale active/high-priority leads, orphan/unparsed artifacts, blocking contradictions, missing truth/checks, approval scope/expiry/replay, blocked budgets, proposals, overdue held/failed notifications, and unfinished/lost workflows. `/healthz` proves liveness; `/readyz` plus dependencies proves readiness.

## Evidence and failures

Report query/report timestamps and counts. Missing dependency report, unavailable authority, stale snapshot, lost/unfinished flow, or zero-row check that should have coverage is not silently healthy.

## Output

Return `ok`, `readiness`, `blockers`, `warnings`, category counts/IDs, `checked_at`, and `report_request`. Route report requests to `data-steward`; direct agent-mode mutation is forbidden. Never repair, write externally, or send channels.

## Reachability (Version 3.0)

The authoritative deterministic check here runs as operator/CI tooling (`scripts/validate_skill_system.py` / `verify_offline.py`), not as a chief runtime action — the chief has no `exec`. As a chief agent-skill this is a review/advisory lens that requests or summarizes the check; the enforcing gate is the release pipeline.
