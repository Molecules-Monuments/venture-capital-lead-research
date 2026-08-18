# Scoring Rubric

> [MUST_CUSTOMIZE] The criterion definitions, weights, evidence coverage
> gates and recommendation thresholds below are examples to edit; the software
> applies them but does not assess whether they predict anything.
> Update the machine rubric and the fixtures together. The policy version is
> frozen at `3.0` for this release — do not bump it.

Policy version: `3.0`

## Authority and prerequisites

The chief owns the recommendation. The qualification analyst produces a score packet from a current compiled-truth snapshot, contradiction check, and trajectory check when dated comparable metrics exist. A hard exclusion, identity conflict, or missing required coverage overrides the numeric result.

## Criterion scale

Each criterion is scored from `0` to `5`:

| Score | Meaning |
|---:|---|
| 0 | Admissible evidence is materially negative |
| 1 | Weak/negative evidence |
| 2 | Some evidence, below threshold |
| 3 | Credible and plausible |
| 4 | Strong, specific evidence |
| 5 | Exceptional, independently supported evidence |

Submitted claims may inform qualitative context but cannot support a persisted
criterion score or verified coverage. Persisted criterion evidence must be a
current verified fact in the exact compiled-truth snapshot. Every criterion has
an explicit evidence state: `positive`, `negative`, `mixed`, `unknown`,
`not_applicable`, or `blocked`. `unknown`, `not_applicable`, and `blocked` have a
null quality score. They are never represented as negative evidence.

## Sample weights — customization required

The bundled weights are an executable example, not a proven investment model.
Replace them with a reviewed, stage/sector-specific rubric and chronological
holdout evidence before deployment. Weights always sum to 100; origin controls
provenance and workflow, never hidden score weight.

| Stable key | Criterion | Weight |
|---|---|---:|
| `thesis_stage_geography_fit` | Thesis, stage, and geography fit | 15 |
| `founder_team_signal` | Founder and team evidence | 15 |
| `problem_product_depth` | Problem and product depth | 15 |
| `technical_differentiation` | Technical differentiation | 10 |
| `traction_adoption` | Traction and adoption | 15 |
| `market_buyer_timing` | Market, buyer, and timing | 10 |
| `business_commercial_evidence` | Business and commercial evidence | 10 |
| `risk_decision_readiness` | Risk and decision readiness | 10 |

`scoring-rubric.v3.json` is the machine authority. Callers never define or
rename weights. A supplied weight map is accepted only when it exactly equals
that file and otherwise fails closed.

## Calculation

For criterion `i`, `points_i = weight_i * score_i / 5`.

`raw_100 = sum(points_i)`. The fixed calculation denominator is 100. An
unknown, not-applicable, or blocked criterion has `quality_score = null` and a
zero arithmetic contribution; this is an explicit calculation convention, not
a claim that evidence quality is zero. Never redistribute its weight. Report
weighted evidence coverage separately. Apply only explicitly evidenced
adjustments:

- blocking contradiction or hard exclusion: recommendation override, no high-priority result;
- material unresolved contradiction: `-5` or `-10`, with cited reason;
- comparable trajectory: integer adjustment from `-5` to `+5`;
- no other implicit confidence/origin bonus.

`final_100 = clamp(raw_100 + adjustments, 0, 100)`.

The adjustment limits above are fixed in the vcops helper (`calculate_score`)
and are not configurable through `scoring-rubric.v3.json`; the rubric file's
configuration surface is its criteria weights, decision-readiness gates, and
recommendation intervals.

`display_5 = round(final_100 / 20, 1)` for display only; recommendations use unrounded `final_100`.

## Complete recommendation intervals

| Unrounded final score | Outcome |
|---:|---|
| `0 <= score < 50` | `pass` |
| `50 <= score < 66` | `watch` |
| `66 <= score < 82` | `research_deeper` |
| `82 <= score <= 100` | `high_priority` |

In interval notation the same four bands are `[0, 50)`, `[50, 66)`, `[66, 82)`
and `[82, 100]` on unrounded `final_100`: contiguous over `[0, 100]` with no gap
and no overlap, and exactly what `scoring-rubric.v3.json` encodes as
`recommendation_intervals`. There is deliberately no display-scale equivalent.

The helper decides the recommendation from unrounded `final_100`, and
`display_5` is not a second spelling of it. `display_5` rounds `final_100 / 20`
to one decimal, so each display value covers a two-point window of `final_100`,
and the window straddles a band edge rather than starting at it. `final_100` is
carried to three decimals, and `display_5 = 4.1` is produced by every value from
`81.001` to `82.999` — of which `81.001`–`81.999` band `research_deeper` and
`82.000`–`82.999` band `high_priority`. `81.000` displays `4.0` and `83.000`
displays `4.2`, so the window is open at both ends; the asymmetry is
round-half-to-even on the exact ties `4.05` and `4.15`. The same half-step
offset sits on the other two edges — `final_100 = 49.900` displays `2.5` but
bands `pass`, and `65.900` displays `3.3` but bands `watch`. Never read a
recommendation off a display value.

Overrides and readiness gates:

- `insufficient_evidence` when identity is not reliable or the rubric's
  evaluated-count, weighted-coverage, or required-criterion gates are not met;
- `needs_human_review` for blocking contradiction, confidentiality/legal issue, approval boundary, or unreliable high-priority evidence;
- `pass` for a hard exclusion.
- A numerical `high_priority` is downgraded to `research_deeper` unless the
  rubric's higher coverage gate and required contradiction/trajectory checks
  are complete.

Each supplied criterion includes `evidence_state`, nullable `quality_score`,
`coverage`, `evidence_quality`, evidence and counterevidence fact IDs,
`rationale`, and `what_would_change`. Evidence IDs must belong to the current
compiled-truth snapshot. Unknown criteria may be omitted, `null`, or explicitly
typed as unknown. Preview decision context contains explicit booleans for
identity reliability, prerequisite-check completion, and override conditions,
plus evidence-bound adjustments. At persistence,
Postgres compiled truth—not the caller—supplies identity reliability and
blocking-contradiction state and any caller mismatch is recorded. A
contradiction adjustment is exactly `-5` or
`-10`; a trajectory adjustment is an integer in `[-5,+5]`.

## Required score packet

Return rubric version, criterion score/weight/points, evidence IDs, confidence reason, raw score, each adjustment, final score, coverage, override, and recommendation. Persist only through the fixed `evaluate-lead` workflow; direct agent-mode `vcops` mutation is forbidden.
