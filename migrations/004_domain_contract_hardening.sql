-- SPDX-License-Identifier: 0BSD
-- OpenClaw Lead Research System 2.0
-- Bind idempotency to request content, freeze evidence history, and enforce lineage.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE leads ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE notification_outbox ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE evaluations ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE document_extractions ADD COLUMN IF NOT EXISTS request_hash TEXT;

DO $block$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='leads_request_hash_check') THEN
    ALTER TABLE leads ADD CONSTRAINT leads_request_hash_check
      CHECK (request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='notification_outbox_request_hash_check') THEN
    ALTER TABLE notification_outbox ADD CONSTRAINT notification_outbox_request_hash_check
      CHECK (request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='evaluations_request_hash_check') THEN
    ALTER TABLE evaluations ADD CONSTRAINT evaluations_request_hash_check
      CHECK (request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='document_extractions_request_hash_check') THEN
    ALTER TABLE document_extractions ADD CONSTRAINT document_extractions_request_hash_check
      CHECK (request_hash IS NULL OR request_hash ~ '^[0-9a-f]{64}$');
  END IF;
END;
$block$;

ALTER TABLE evaluations DROP CONSTRAINT IF EXISTS evaluations_recommendation_band_check;
ALTER TABLE evaluations DROP CONSTRAINT IF EXISTS evaluations_check;
ALTER TABLE evaluations DROP CONSTRAINT IF EXISTS evaluations_score_band_check;
ALTER TABLE evaluations ALTER COLUMN total_score TYPE NUMERIC(6,3);
ALTER TABLE evaluation_criteria ALTER COLUMN weighted_points TYPE NUMERIC(6,3);
ALTER TABLE evaluations ADD CONSTRAINT evaluations_recommendation_band_check
  CHECK (recommendation_band IN (
    'pass', 'watch', 'research_deeper', 'high_priority',
    'insufficient_evidence', 'needs_human_review'
  ));
ALTER TABLE evaluations ADD CONSTRAINT evaluations_score_band_check CHECK (
  recommendation_band IN ('insufficient_evidence', 'needs_human_review') OR
  (total_score >= 0 AND total_score < 50 AND recommendation_band = 'pass') OR
  (total_score >= 50 AND total_score < 66 AND recommendation_band = 'watch') OR
  (total_score >= 66 AND total_score < 82 AND recommendation_band = 'research_deeper') OR
  (total_score >= 82 AND total_score <= 100 AND recommendation_band = 'high_priority')
);

ALTER TABLE evaluations
  DROP CONSTRAINT IF EXISTS evaluations_lead_id_evidence_packet_hash_rubric_version_key;
CREATE UNIQUE INDEX IF NOT EXISTS evaluations_request_uidx
  ON evaluations (lead_id, request_hash) WHERE request_hash IS NOT NULL;

ALTER TABLE memos DROP CONSTRAINT IF EXISTS memos_content_sha256_key;
CREATE UNIQUE INDEX IF NOT EXISTS memos_content_lineage_uidx
  ON memos (lead_id, compiled_truth_id, evaluation_id, content_sha256);

CREATE TABLE IF NOT EXISTS memo_citations (
  memo_id BIGINT NOT NULL REFERENCES memos(id) ON DELETE RESTRICT,
  fact_id BIGINT NOT NULL REFERENCES facts(id) ON DELETE RESTRICT,
  source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
  citation_label TEXT NOT NULL CHECK (btrim(citation_label) <> ''),
  source_locator TEXT NOT NULL CHECK (btrim(source_locator) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (memo_id, fact_id, source_id, citation_label)
);
CREATE INDEX IF NOT EXISTS memo_citations_fact_idx ON memo_citations (fact_id, source_id);

CREATE OR REPLACE FUNCTION prevent_domain_history_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
BEGIN
  RAISE EXCEPTION '% is append-only; create a superseding/versioned row', TG_TABLE_NAME
    USING ERRCODE = '55000';
END;
$function$;

DO $block$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'facts', 'fact_sources', 'document_facts', 'compiled_truth_facts',
    'evaluation_criteria', 'memo_citations',
    -- The contradiction/trajectory evidence-linkage tables are history like their
    -- siblings above: the runtime only ever INSERTs and SELECTs them, so pin them
    -- append-only too rather than leaving them the one UPDATE/DELETE-able exception.
    'contradiction_facts', 'trajectory_points'
  ]
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_trigger
      WHERE tgrelid=to_regclass(table_name) AND tgname=table_name || '_append_only'
    ) THEN
      EXECUTE format(
        'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION prevent_domain_history_mutation()',
        table_name || '_append_only', table_name
      );
    END IF;
  END LOOP;
END;
$block$;

CREATE OR REPLACE FUNCTION guard_workflow_lineage()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  stored_company BIGINT;
BEGIN
  IF NEW.lead_id IS NOT NULL THEN
    SELECT company_id INTO stored_company FROM leads WHERE id=NEW.lead_id;
    IF NOT FOUND THEN
      RAISE EXCEPTION 'workflow lead does not exist' USING ERRCODE='23503';
    END IF;
    IF stored_company IS NULL OR NEW.company_id IS DISTINCT FROM stored_company THEN
      RAISE EXCEPTION 'workflow lead/company lineage mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS workflow_runs_lineage ON workflow_runs;
CREATE TRIGGER workflow_runs_lineage
  BEFORE INSERT OR UPDATE OF lead_id,company_id ON workflow_runs
  FOR EACH ROW EXECUTE FUNCTION guard_workflow_lineage();

CREATE OR REPLACE FUNCTION guard_fact_lineage()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  stored_company BIGINT;
  run_lead BIGINT;
  run_company BIGINT;
BEGIN
  IF NEW.lead_id IS NOT NULL THEN
    SELECT company_id INTO stored_company FROM leads WHERE id=NEW.lead_id;
    IF NOT FOUND OR stored_company IS NULL OR stored_company IS DISTINCT FROM NEW.company_id THEN
      RAISE EXCEPTION 'fact lead/company lineage mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  IF NEW.workflow_run_id IS NOT NULL THEN
    SELECT lead_id,company_id INTO run_lead,run_company FROM workflow_runs WHERE id=NEW.workflow_run_id;
    IF NOT FOUND OR (run_lead IS NOT NULL AND run_lead IS DISTINCT FROM NEW.lead_id)
       OR (run_company IS NOT NULL AND run_company IS DISTINCT FROM NEW.company_id) THEN
      RAISE EXCEPTION 'fact workflow lineage mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS facts_lineage ON facts;
CREATE TRIGGER facts_lineage BEFORE INSERT ON facts
  FOR EACH ROW EXECUTE FUNCTION guard_fact_lineage();

CREATE OR REPLACE FUNCTION guard_compiled_truth_lineage()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  stored_company BIGINT;
  run_lead BIGINT;
  run_company BIGINT;
BEGIN
  SELECT company_id INTO stored_company FROM leads WHERE id=NEW.lead_id;
  IF NOT FOUND OR stored_company IS NULL OR stored_company IS DISTINCT FROM NEW.company_id THEN
    RAISE EXCEPTION 'compiled truth lead/company lineage mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.workflow_run_id IS NOT NULL THEN
    SELECT lead_id,company_id INTO run_lead,run_company FROM workflow_runs WHERE id=NEW.workflow_run_id;
    IF NOT FOUND OR run_lead IS DISTINCT FROM NEW.lead_id OR run_company IS DISTINCT FROM NEW.company_id THEN
      RAISE EXCEPTION 'compiled truth workflow lineage mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS compiled_truth_lineage ON compiled_truth;
CREATE TRIGGER compiled_truth_lineage
  BEFORE INSERT OR UPDATE OF lead_id,company_id,workflow_run_id ON compiled_truth
  FOR EACH ROW EXECUTE FUNCTION guard_compiled_truth_lineage();

CREATE OR REPLACE FUNCTION guard_compiled_truth_fact()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  stored_status TEXT;
  fact_lead BIGINT;
  fact_company BIGINT;
  truth_lead BIGINT;
  truth_company BIGINT;
BEGIN
  SELECT fact_status,lead_id,company_id INTO stored_status,fact_lead,fact_company
  FROM facts WHERE id=NEW.fact_id;
  SELECT lead_id,company_id INTO truth_lead,truth_company
  FROM compiled_truth WHERE id=NEW.compiled_truth_id;
  IF fact_lead IS DISTINCT FROM truth_lead OR fact_company IS DISTINCT FROM truth_company THEN
    RAISE EXCEPTION 'compiled truth fact lineage mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.support_role='current' AND stored_status <> 'verified_fact' THEN
    RAISE EXCEPTION 'current compiled truth requires verified facts (fact_id=%)', NEW.fact_id
      USING ERRCODE='23514';
  END IF;
  IF NEW.support_role='current' AND NOT EXISTS (
    SELECT 1 FROM fact_sources WHERE fact_id=NEW.fact_id
  ) THEN
    RAISE EXCEPTION 'current compiled truth requires resolvable fact provenance (fact_id=%)', NEW.fact_id
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION guard_evaluation_lineage()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  truth_lead BIGINT;
  truth_company BIGINT;
  truth_status TEXT;
  truth_hash TEXT;
  run_lead BIGINT;
  run_company BIGINT;
BEGIN
  SELECT lead_id,company_id,status,evidence_packet_hash
    INTO truth_lead,truth_company,truth_status,truth_hash
  FROM compiled_truth WHERE id=NEW.compiled_truth_id;
  IF NOT FOUND OR truth_lead IS DISTINCT FROM NEW.lead_id
     OR truth_hash IS DISTINCT FROM NEW.evidence_packet_hash THEN
    RAISE EXCEPTION 'evaluation compiled-truth lineage mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.status='final' AND truth_status <> 'current' THEN
    RAISE EXCEPTION 'final evaluation requires current compiled truth' USING ERRCODE='23514';
  END IF;
  IF NEW.workflow_run_id IS NOT NULL THEN
    SELECT lead_id,company_id INTO run_lead,run_company FROM workflow_runs WHERE id=NEW.workflow_run_id;
    IF NOT FOUND OR run_lead IS DISTINCT FROM NEW.lead_id OR run_company IS DISTINCT FROM truth_company THEN
      RAISE EXCEPTION 'evaluation workflow lineage mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS evaluations_lineage ON evaluations;
CREATE TRIGGER evaluations_lineage
  BEFORE INSERT OR UPDATE OF lead_id,workflow_run_id,compiled_truth_id,status,evidence_packet_hash ON evaluations
  FOR EACH ROW EXECUTE FUNCTION guard_evaluation_lineage();

CREATE OR REPLACE FUNCTION guard_memo_lineage()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  truth_lead BIGINT;
  truth_hash TEXT;
  evaluation_lead BIGINT;
  evaluation_truth BIGINT;
  run_lead BIGINT;
BEGIN
  SELECT lead_id,evidence_packet_hash INTO truth_lead,truth_hash
  FROM compiled_truth WHERE id=NEW.compiled_truth_id;
  SELECT lead_id,compiled_truth_id INTO evaluation_lead,evaluation_truth
  FROM evaluations WHERE id=NEW.evaluation_id;
  IF NOT FOUND OR truth_lead IS DISTINCT FROM NEW.lead_id
     OR evaluation_lead IS DISTINCT FROM NEW.lead_id
     OR evaluation_truth IS DISTINCT FROM NEW.compiled_truth_id
     OR truth_hash IS DISTINCT FROM NEW.frozen_evidence_hash THEN
    RAISE EXCEPTION 'memo evaluation/compiled-truth lineage mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.workflow_run_id IS NOT NULL THEN
    SELECT lead_id INTO run_lead FROM workflow_runs WHERE id=NEW.workflow_run_id;
    IF NOT FOUND OR run_lead IS DISTINCT FROM NEW.lead_id THEN
      RAISE EXCEPTION 'memo workflow lineage mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS memos_lineage ON memos;
CREATE TRIGGER memos_lineage
  BEFORE INSERT OR UPDATE OF lead_id,workflow_run_id,compiled_truth_id,evaluation_id,frozen_evidence_hash ON memos
  FOR EACH ROW EXECUTE FUNCTION guard_memo_lineage();

CREATE OR REPLACE FUNCTION guard_memo_citation_lineage()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  truth_id BIGINT;
BEGIN
  SELECT compiled_truth_id INTO truth_id FROM memos WHERE id=NEW.memo_id;
  IF NOT FOUND OR NOT EXISTS (
    SELECT 1
    FROM compiled_truth_facts ctf
    JOIN fact_sources fs ON fs.fact_id=ctf.fact_id
    WHERE ctf.compiled_truth_id=truth_id AND ctf.support_role='current'
      AND ctf.fact_id=NEW.fact_id AND fs.source_id=NEW.source_id
  ) THEN
    RAISE EXCEPTION 'memo citation is outside compiled-truth provenance' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS memo_citations_lineage ON memo_citations;
CREATE TRIGGER memo_citations_lineage BEFORE INSERT ON memo_citations
  FOR EACH ROW EXECUTE FUNCTION guard_memo_citation_lineage();

REVOKE UPDATE ON facts,fact_sources,document_facts,compiled_truth_facts,evaluation_criteria
  FROM openclaw_runtime;
GRANT SELECT,INSERT ON memo_citations TO openclaw_runtime;

COMMIT;
