# Missing Data Handling

Policy version: `3.0`

## Canonical states

Use exactly:

- `unknown`: not established;
- `not_disclosed`: likely known by the company but not disclosed;
- `not_applicable`: field does not apply;
- `not_evidenced`: a claim exists without admissible support;
- `extraction_failed`: source exists but extraction failed;
- `conflicting`: comparable evidence cannot both be true;
- `stale`: evidence is too old for the present claim.

`company_submitted_claim` is an evidence status, not a missing-data value.

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
