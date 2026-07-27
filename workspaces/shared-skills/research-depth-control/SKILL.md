---
name: research-depth-control
description: Select and check a bounded research profile consistent with OpenClaw child-agent limits, source budgets, runtime, cost, and approval.
---

# Research Depth Control

## Inputs

- Lead/company, decision question, memory result, requested profile, agent/source/runtime/cost proposal, connector classes, and supplied budget policy.

## Contract

Choose the lowest sufficient profile. Version 3 caps (sample-fund numbers mirroring `research_depth.md`, which is `[MUST_CUSTOMIZE]` — retune both together): `triage` 1 child/8 sources/15 min/no paid; `standard` 3 children/25 sources/45 min/no paid by default; `deep_diligence` 3 concurrent children/60 sources/240 min and valid scoped approval for expansion or paid use. The runtime deterministically enforces only child concurrency and run timeout; source counts, minutes, and paid-connector budgets are this skill's checked-and-reported discipline. Decompose more than three specialist tasks into sequential waves; never promise five simultaneous children. Record actual usage against budget.

## Evidence and failures

Memory lookup is mandatory. Missing approval, excess runtime/children/sources/cost, connector restriction, or unclear decision question returns blocked. Expired or consumed approval cannot expand a run.

## Output

Return `profile`, `limits`, `wave_plan`, `paid_allowed`, `approval_id`, `blockers`, `usage`, and `persistence_request`. Route persistence requests to `data-steward`; direct agent-mode mutation is forbidden. No connector purchase, external write, or channel send.
