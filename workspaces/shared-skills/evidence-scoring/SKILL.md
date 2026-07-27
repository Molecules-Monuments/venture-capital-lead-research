---
name: evidence-scoring
description: Interpret a supplied custom rubric and deterministic score artifact while keeping evidence state, evidence quality, and coverage distinct.
---

# Evidence Scoring

## Inputs

- Current compiled-truth snapshot ID/time/hash, contradiction and trajectory checks, complete custom rubric ID/version/hash and stage/sector profile, evidence coverage, and deterministic calculation artifact when a score is requested.

## Contract

Apply hard exclusions first. Reconcile every rubric criterion and weight with the supplied calculation artifact and every scored criterion with admissible evidence/counterevidence. Never substitute a universal rubric or hard-coded weights for the supplied version.

For each criterion, keep evidence state, evidence quality, and coverage separate. Positive, negative, mixed, unknown, not-applicable, and blocked are not interchangeable. Missing or inadmissible evidence remains unknown with a null quality score; do not silently turn it into zero or redistribute its weight. Negative evidence remains negative rather than being hidden in a coverage ratio.

No arithmetic is performed by the model. If a valid deterministic calculation ID/output is absent or does not reconcile, return `not_computed` with null totals. Keep adjustments attributable to named supplied rules and calculation IDs. Origin, prestige, and narrative confidence are never hidden score inputs.

## Evidence and failures

Surface rubric mismatch, unknown criteria, invalid evidence references, unsupported adjustment, incomplete check prerequisites, and calculation inconsistency. Require contradiction and trajectory checks before `high_priority`. Prioritize next research by its ability to change the gate result.

## Output boundary

Validate the complete response against `/workspaces/schemas/qualification-analyst.output.schema.json`. The canonical schema, not this prose, controls all fields, types, enums, and failure states.

Direct research, calculation, mutation, external write, delegation, and channel send are forbidden.
