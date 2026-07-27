---
name: outbound-sourcing
description: Discover thesis-relevant candidates from approved public sources within a bounded research budget.
---

# Outbound Sourcing

## Inputs

- Supplied thesis/exclusion/source policy, approved source classes, explicit query/result/fetch/source/time limits, stopping threshold, and prior memory/source-yield summary.

## Contract

Collect canonical name/domain, stable candidate and source references, observed signal, source/observed/retrieval dates, and origin subtype. Prefer direct public primary sources and distinguish independent corroboration from circular repetition. Deduplicate exact domains before proposing fuzzy candidates. Record thesis gaps, novelty, and credible outlier rationale so discovery does not collapse into thesis confirmation. Stop at budget, marginal-yield, rate, or terms limits; paid or login-gated connectors need a matching approval.

## Evidence and failures

Every candidate cites resolvable evidence and its discovery sources. Report assigned versus used budget and results-inspected/candidate-yield by source, including zero yield. Robots/terms uncertainty, identity ambiguity, insufficient provenance, private data, or connector limits are blockers or risks, never bypassed.

## Output

Return exactly one object valid against [`../../schemas/outbound-scout.output.schema.json`](../../schemas/outbound-scout.output.schema.json). The schema is the sole authority for fields, budget counters, enums, required values, and nullability; do not maintain a parallel output definition here. Route approved candidates through `data-steward` and the fixed `outbound-scout` workflow; direct agent-mode mutation is forbidden. Never contact founders, create accounts, bypass access controls, write externally, or send channel messages.
