---
name: knowledge-modeling
description: Produce typed entity, fact, source, event, relationship, and merge-proposal records with temporal provenance.
---

# Knowledge Modeling

## Inputs

- Evidence packet, canonical lookup results, supplied knowledge schema/policy, and source/artifact/message identifiers.

## Contract

Model stable entities and aliases separately. Every material fact has a status, source, observed/source/valid time, confidence, and actor/run provenance. Represent relationships and events explicitly. Do not overwrite prior facts; supersede with temporal records. Possible duplicates become merge proposals and require human approval.

## Evidence and failures

Reject orphan facts, invalid enum/state transitions, missing source links, impossible validity ranges, or ambiguous identity. Silence remains unknown.

## Output

Return `entities`, `aliases`, `facts`, `fact_sources`, `events`, `relationships`, `merge_proposals`, `missing_data`, `warnings`, and `persistence_request`. Route persistence requests to `data-steward`; direct agent-mode mutation is forbidden and unsupported operations require the operator helper. No external write or channel send.
