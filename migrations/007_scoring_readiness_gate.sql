-- SPDX-License-Identifier: 0BSD
-- OpenClaw Lead Research System 3.0
-- Permit an evidence-readiness downgrade without falsifying the numeric score.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

ALTER TABLE evaluations DROP CONSTRAINT IF EXISTS evaluations_score_band_check;
ALTER TABLE evaluations ADD CONSTRAINT evaluations_score_band_check CHECK (
  recommendation_band IN ('insufficient_evidence', 'needs_human_review') OR
  (total_score >= 0 AND total_score < 50 AND recommendation_band = 'pass') OR
  (total_score >= 50 AND total_score < 66 AND recommendation_band = 'watch') OR
  (total_score >= 66 AND total_score < 82 AND recommendation_band = 'research_deeper') OR
  (total_score >= 82 AND total_score <= 100 AND recommendation_band = 'high_priority') OR
  (
    total_score >= 82 AND total_score <= 100
    AND recommendation_band = 'research_deeper'
    AND scoring_details ->> 'override' = 'high_priority_prerequisites_missing'
  ) OR
  -- A hard exclusion bands to 'pass' at whatever the criteria actually scored:
  -- an excluded-but-strong company (good team, wrong geography/sector/stage) is
  -- the normal case, and scoring-rubric.md documents `pass` as the hard-exclusion
  -- outcome. Zeroing total_score instead would falsify the numeric score, which
  -- is exactly what this migration exists to avoid, so admit the band on the
  -- recorded override rather than on the score.
  (
    total_score >= 0 AND total_score <= 100
    AND recommendation_band = 'pass'
    AND scoring_details ->> 'override' = 'hard_exclusion'
  )
);

COMMIT;
