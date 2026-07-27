---
name: lead-routing
description: Classify a candidate’s origin and select bounded skills and agents from the canonical resolver inventory.
---

# Lead Routing

## Inputs

- Trust decision, raw lead context, source metadata, memory-lookup summary, and supplied resolver/origin policy packet.

## Contract

Assign the most specific supported origin and confidence. Select only names from the supplied canonical inventory. Before selecting a worker, define its decision question, required information, acceptance condition, and stop condition. Return the minimum acyclic route, with stable step IDs and explicit dependencies; use parallel steps only when they have no hidden data dependency. Unknown origin receives no scoring bonus or authority.

## Evidence and failures

Cite the metadata supporting origin and every route condition. Required-agent and required-skill summaries must equal the union in the steps. Missing identity, ambiguous origin, dangling or cyclic dependency, missing evaluation, or absent allowlist yields a blocked route for chief review.

## Output

Return exactly one object valid against [`../../schemas/lead-router.output.schema.json`](../../schemas/lead-router.output.schema.json). The schema is the sole authority for fields, inventory names, enums, required values, and nullability; do not maintain a parallel output definition here. Route persistence requests to `data-steward`; direct agent-mode mutation is forbidden. No external write or channel send.
