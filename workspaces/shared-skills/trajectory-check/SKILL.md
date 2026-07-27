---
name: trajectory-check
description: Validate comparable dated metric tuples and interpret a supplied deterministic change artifact without model-generated arithmetic.
---

# Trajectory Check

## Inputs

- Lead/company identifiers, supplied trajectory policy, typed observations matching the traction schema, and a deterministic calculation ID/output when numeric change is requested.

## Contract

Compatibility is decided before direction. Require the same metric definition, unit and currency basis, compatible period treatment, and compatible cohort. Require at least two non-overlapping dated observations for `up`, `down`, or `flat`; require at least three for `volatile`. One point is `unknown`. Never compare ARR to revenue, gross to net, different currencies without a cited basis, or incompatible cohorts. Ordinary dated movement is not a contradiction.

Do not calculate or normalize values in model prose. Validate raw and normalized values against the supplied deterministic artifact and cite its ID. If it is missing, inconsistent, or not reproducible from the typed inputs, return `not_comparable` or `unknown` with null change values rather than repairing it.

## Evidence and failures

Cite observation, fact, source, and calculation IDs plus dates, units, cohort, normalization, compatibility decision, and limits. Treat a current submitted claim as current but unverified; do not upgrade its fact status. Incompatible definitions, parse failure, overlapping validity, weak source reconciliation, or unclear direction remains explicit.

## Output boundary

Represent observations and comparisons only through `/workspaces/schemas/traction-analyst.output.schema.json`, especially `#/$defs/metricObservation` and `#/$defs/comparison`. The canonical schema, not this prose, controls field names and types.

Direct mutation, external write, delegation, and channel send are forbidden.
