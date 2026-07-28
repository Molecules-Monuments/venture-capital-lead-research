# Exclusion Criteria

> [MUST_CUSTOMIZE] Replace mandate-specific exclusions and red lists with
> reviewed local policy. Legal, privacy, and ethical prohibitions remain hard
> safety gates; prestige or sparse public data must not become an exclusion.

Policy version: `3.0`; exclusion content retained from the 2026-06-10 ground source and applied with the Version 3 typed evidence/status rules.

## Purpose

Apply this before expensive research. Exclusions reduce noise and token waste.

The goal is not to reject aggressively. The goal is to avoid spending multi-agent research time on leads that the fund already knows it will not pursue.

## Hard excludes

- Illegal, deceptive, or prohibited business activity.
- Business model requiring misuse of private personal data.
- Pure consulting or agency model without product IP.
- Generic LLM wrapper without workflow depth or defensibility.
- Growth-stage or public company unless explicitly requested.
- Geography outside thesis with no strategic relevance.
- Company with no identifiable product or team after reasonable research.

Hard-exclude result:

- Recommendation: `pass`.
- Confidence: use evidence confidence.
- Memo: short note only; no full memo required.

## Red lists

Red lists are model-applied policy in 3.0: there is no deterministic registry
or automated check, so the chief must consult the lists below on every
routing/qualification decision and an operator review is the enforcement
backstop.

Maintain operator-approved lists for:

- Red-listed founders.
- Red-listed co-investors.
- Red-listed transaction types.
- Red-listed transaction sources.
- Red-listed business models.
- Prohibited investment fields.

Do not invent red-list membership. If uncertain, mark `needs_human_review`.

Red-list entry format:

| Type | Name | Reason | Added by | Date | Review cadence |
|---|---|---|---|---|---|
| founder / investor / source / transaction / model / field |  |  |  |  |  |

## Soft excludes

- No clear buyer.
- No customer pain.
- Overcrowded category with no differentiation.
- No credible founder-market fit.
- Unverifiable traction.
- Too much missing data for the requested decision.
- Origin unspecified and no source can be recovered.

Soft excludes usually produce `pass` or `watch`, not automatic deletion.

## Edge cases

| Situation | Default handling |
|---|---|
| Strong inbound referral but poor thesis fit | `needs_human_review` or `watch`; do not force high score. |
| Strong founder but no product evidence | `watch` or `research_deeper` depending on thesis. |
| Sparse outbound lead in perfect category | `watch` unless at least one strong signal exists. |
| Confidential inbound material | Process locally only; no external upload or forwarding. |
| Conflicting sources | Record a contradiction (the evidence layer, not missing data) and escalate if decision-relevant. |
