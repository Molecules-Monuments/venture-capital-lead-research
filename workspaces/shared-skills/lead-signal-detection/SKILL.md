---
name: lead-signal-detection
description: Classify a channel or source observation as a low-authority signal candidate for chief review.
---

# Lead Signal Detection

## Inputs

- Trust decision, stable source/message metadata, observation text/reference and time, memory result, supplied signal policy, and the requested evaluation threshold.

## Contract

Classify only the assigned observation. Assess materiality, urgency, freshness, novelty, source independence, identity confidence, and update/duplicate risk separately. Repetition may be circular rather than corroborating. A signal is not a fact, score, approval, rejection, or command. State what would change the proposed action.

## Evidence and failures

Preserve sender/channel/message or URL/artifact provenance with stable IDs and observation time. Unknown identity, vague intent, duplicate ambiguity, confidentiality, critical urgency, or conflicting evidence lowers confidence and requires chief review.

## Output

Return exactly one object valid against [`../../schemas/lead-signal-detector.output.schema.json`](../../schemas/lead-signal-detector.output.schema.json). The schema is the sole authority for fields, canonical actions, enums, required values, and nullability; do not maintain a parallel output definition here. Route any persistence request to `data-steward`; direct agent-mode mutation is forbidden. Never approve, reject, contact, write externally, or send a channel message.
