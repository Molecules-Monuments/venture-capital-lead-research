# Trajectory Policy

Policy version: `3.0`

## Comparability

Compare only the same entity, metric definition, unit/currency, period length, cohort, and gross/net basis. Each observation requires value, effective/observed date, evidence status, fact ID, and source ID.

## Direction

- one point: `unknown_baseline`;
- at least two non-overlapping comparable points: `up`, `down`, or `flat`;
- at least three comparable points with material reversals: `volatile`;
- incompatible or unparseable points: `not_comparable`.

Parse decimal and magnitude exactly: `1.2m = 1,200,000`; `900k = 900,000`. Preserve original text and normalized value. A move from 900k to 1.2m is up; a newer 900k after 1.2m is down, not automatically a contradiction.

Do not convert currencies without a dated cited FX rate. Do not treat hiring, press, stars, downloads, or community activity as revenue proof. Submitted time series remain submitted claims.

## Score use

A trajectory adjustment is allowed only for comparable decision-relevant evidence and is bounded to `-5..+5` points on the 100-point score. Return the calculation and evidence IDs.
