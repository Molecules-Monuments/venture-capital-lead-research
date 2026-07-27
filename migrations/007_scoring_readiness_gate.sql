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
  )
);

COMMIT;
