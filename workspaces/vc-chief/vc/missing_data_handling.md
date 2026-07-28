# Missing Data Handling

Policy version: `3.0`

## Canonical semantics and per-lane vocabularies

The semantic distinctions below are canonical. They are deliberately encoded
in two lane-specific schema vocabularies, because intake lanes and research
lanes miss data for different reasons; use the exact enum of the schema you
are writing:

| Semantic distinction | Intake/sourcing lanes — `missing_data[].status` (lead-router, lead-signal-detector, inbound-intake-analyst, document-intake-analyst, outbound-scout) | Research/analysis lanes — `missing_data[].state` (founder-researcher, traction-analyst, market-mapper, qualification-analyst, memo-writer, vc-chief) |
|---|---|---|
| Not established / not found | `absent` | `missing` |
| Likely known by the company but not disclosed | `not_disclosed` | `missing` (state the non-disclosure in `reason`) |
| Field does not apply | `not_applicable` | `not_applicable` |
| Source exists but extraction failed | `extraction_failed` | `blocked` (name the failed source in `reason`) |
| Deliberately out of the lane's scope | `not_requested` | `not_applicable` (record the scope bound in `reason`) |
| Cannot be established with authorized effort | — (intake does not research) | `unknown` |
| Access or policy prevents research | — | `blocked` |

Intake-lane items carry `field`, `status`, `reason` (inbound intake adds
`source_ref`); research-lane items carry `field`, `state`, `reason`, and
`evidence_needed`. The `data-steward` envelope's `missing_data` is a free-text
list naming operation-level omissions; it is not an evidence vocabulary.

Evidence that exists but is unverified, contradicted, or too old is not
"missing data": that belongs to the evidence layer — fact statuses
`submitted_claim`, `contradicted`, `stale`, `unknown`, and `retracted`, plus
contradiction records. A claim without admissible support stays a
`submitted_claim`; `company_submitted_claim` wording in reports reflects that
evidence status, not a missing-data value.

## Rules

1. Do not infer from silence, logos, domains, language, employee lists, or model prior knowledge.
2. Keep value, missing state, evidence status, source ID, confidence, and observed/source dates separate.
3. Financials are never estimated unless the operator explicitly requests a labeled scenario model.
4. Uploaded values remain submitted claims with page/sheet/cell provenance until verified.
5. A parser failure is not the same as an absent value.
6. Missing evidence contributes zero in the fixed scoring denominator. Never redistribute its weight or raise another criterion because data is absent.
7. If minimum score coverage is not met, use `insufficient_evidence`; do not manufacture a numeric recommendation.
8. Never reward missing evidence, directly or through redistribution, confidence, origin, or adjustment bonuses.

## Required language

Use “the company claims”, “public evidence supports”, “no admissible evidence found”, and “extraction failed”. Never state a submitted or inferred value as established fact.
