---
name: inbound-intake
description: Normalize an inbound submission into a provenance-rich, non-authoritative lead-intake packet.
---

# Inbound Intake

## Inputs

- Trust decision, stable channel/message/referrer metadata, received time, raw submission reference, document extraction results, supplied governance decisions, and intake policy.

## Contract

Normalize company/referrer/origin, trust, sender authority, confidentiality, storage tier, retention, consent, lawful basis, documents, and stable claim/source references. Apply supplied governance decisions; do not invent consent or make a legal determination. Keep submitter statements as `submitted_claim`; only independently evidenced public items supplied in the task may be `verified_fact`. Preserve typed missingness, including whether a field was not requested. Request memory lookup before canonical creation.

## Evidence and failures

Every claim cites a message, artifact/page/cell, or URL using a stable reference. Unknown sender authority, consent or lawful-basis gap, ambiguous confidentiality, unsafe document, identity collision, or missing provenance yields `needs_human_review`; it never grants authority. Minimize personal data to the supplied stable identifier and label.

## Output

Return exactly one object valid against [`../../schemas/inbound-intake-analyst.output.schema.json`](../../schemas/inbound-intake-analyst.output.schema.json). The schema is the sole authority for fields, governance statuses, typed missingness, enums, required values, and nullability; do not maintain a parallel output definition here. Route approved intake persistence through `data-steward` and the fixed workflow that matches the submission's origin — the three are not interchangeable and `inbound-intake` serves only the first: `inbound-intake` for an operator document dropped under `/inbox` (it requires a `document_path` below `/inbox`), `inbound-text-intake` for a text-only submission with no document, and `document-lead-intake` for a channel attachment (it requires the signed `trusted_context` and the `extraction_id` from `document-ingest`). Naming the wrong one fails closed at `vcrun` argument validation. Direct agent-mode mutation is forbidden. No reply, outreach, upload, external write, or channel send.
