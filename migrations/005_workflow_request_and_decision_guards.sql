-- OpenClaw Lead Research System 2.0
-- Claim whole workflow payloads before business mutation and freeze decision guards.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE IF NOT EXISTS workflow_requests (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  workflow_id TEXT NOT NULL CHECK (btrim(workflow_id) <> ''),
  idempotency_key TEXT NOT NULL CHECK (btrim(idempotency_key) <> ''),
  request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
  request_payload JSONB NOT NULL CHECK (jsonb_typeof(request_payload) = 'object'),
  document_sha256 TEXT CHECK (document_sha256 IS NULL OR document_sha256 ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (workflow_id, idempotency_key)
);

ALTER TABLE document_extractions
  ADD COLUMN IF NOT EXISTS workflow_request_id BIGINT REFERENCES workflow_requests(id) ON DELETE RESTRICT;

CREATE UNIQUE INDEX IF NOT EXISTS document_extractions_workflow_request_uidx
  ON document_extractions (workflow_request_id)
  WHERE workflow_request_id IS NOT NULL;

ALTER TABLE compiled_truth
  ADD COLUMN IF NOT EXISTS fact_history JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE compiled_truth
  ADD COLUMN IF NOT EXISTS contradiction_history JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE compiled_truth
  ADD COLUMN IF NOT EXISTS trajectory_history JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE compiled_truth
  ADD COLUMN IF NOT EXISTS decision_guards JSONB NOT NULL
    DEFAULT '{"state_complete":false,"identity_reliable":false,"blocking_contradiction":false}'::jsonb;

DO $block$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='compiled_truth_fact_history_check') THEN
    ALTER TABLE compiled_truth ADD CONSTRAINT compiled_truth_fact_history_check
      CHECK (jsonb_typeof(fact_history) = 'array');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='compiled_truth_contradiction_history_check') THEN
    ALTER TABLE compiled_truth ADD CONSTRAINT compiled_truth_contradiction_history_check
      CHECK (jsonb_typeof(contradiction_history) = 'array');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='compiled_truth_trajectory_history_check') THEN
    ALTER TABLE compiled_truth ADD CONSTRAINT compiled_truth_trajectory_history_check
      CHECK (jsonb_typeof(trajectory_history) = 'array');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='compiled_truth_decision_guards_check') THEN
    ALTER TABLE compiled_truth ADD CONSTRAINT compiled_truth_decision_guards_check CHECK (
      jsonb_typeof(decision_guards) = 'object'
      AND jsonb_typeof(decision_guards->'state_complete') = 'boolean'
      AND jsonb_typeof(decision_guards->'identity_reliable') = 'boolean'
      AND jsonb_typeof(decision_guards->'blocking_contradiction') = 'boolean'
    );
  END IF;
END;
$block$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid='workflow_requests'::regclass AND tgname='workflow_requests_append_only'
  ) THEN
    CREATE TRIGGER workflow_requests_append_only
      BEFORE UPDATE OR DELETE ON workflow_requests
      FOR EACH ROW EXECUTE FUNCTION prevent_domain_history_mutation();
  END IF;
END;
$block$;

CREATE OR REPLACE FUNCTION guard_document_workflow_request()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  claimed_workflow TEXT;
  claimed_key TEXT;
  claimed_sha TEXT;
  artifact_sha TEXT;
  run_workflow TEXT;
  run_key TEXT;
BEGIN
  IF NEW.workflow_request_id IS NULL THEN
    RETURN NEW;
  END IF;

  SELECT workflow_id,idempotency_key,document_sha256
    INTO claimed_workflow,claimed_key,claimed_sha
    FROM workflow_requests WHERE id=NEW.workflow_request_id;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'document workflow request does not exist' USING ERRCODE='23503';
  END IF;
  IF claimed_sha IS NULL OR claimed_key IS DISTINCT FROM NEW.idempotency_key THEN
    RAISE EXCEPTION 'document extraction request/key mismatch' USING ERRCODE='23514';
  END IF;

  SELECT sha256 INTO artifact_sha FROM evidence_artifacts WHERE id=NEW.artifact_id;
  IF artifact_sha IS DISTINCT FROM claimed_sha THEN
    RAISE EXCEPTION 'document extraction hash differs from claimed workflow request' USING ERRCODE='23514';
  END IF;

  IF NEW.workflow_run_id IS NOT NULL THEN
    SELECT workflow_id,idempotency_key INTO run_workflow,run_key
      FROM workflow_runs WHERE id=NEW.workflow_run_id;
    IF NOT FOUND OR run_workflow IS DISTINCT FROM claimed_workflow OR run_key IS DISTINCT FROM claimed_key THEN
      RAISE EXCEPTION 'document extraction workflow lineage mismatch' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS document_extractions_workflow_request_lineage ON document_extractions;
CREATE TRIGGER document_extractions_workflow_request_lineage
  BEFORE INSERT OR UPDATE OF artifact_id,workflow_run_id,idempotency_key,workflow_request_id
  ON document_extractions
  FOR EACH ROW EXECUTE FUNCTION guard_document_workflow_request();

REVOKE ALL ON workflow_requests FROM openclaw_runtime;
GRANT SELECT, INSERT ON workflow_requests TO openclaw_runtime;
GRANT USAGE, SELECT ON SEQUENCE workflow_requests_id_seq TO openclaw_runtime;

COMMIT;
