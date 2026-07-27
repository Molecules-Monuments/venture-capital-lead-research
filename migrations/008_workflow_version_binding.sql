-- SPDX-License-Identifier: 0BSD
-- OpenClaw Lead Research System 3.0
-- Bind idempotent workflow state to the exact package and policy semantics.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

ALTER TABLE workflow_requests
  ADD COLUMN IF NOT EXISTS workflow_version TEXT,
  ADD COLUMN IF NOT EXISTS policy_version TEXT;

UPDATE workflow_requests
SET workflow_version = COALESCE(workflow_version, 'legacy-unversioned'),
    policy_version = COALESCE(policy_version, 'legacy-unversioned')
WHERE workflow_version IS NULL OR policy_version IS NULL;

ALTER TABLE workflow_requests
  ALTER COLUMN workflow_version SET DEFAULT '3.0.0',
  ALTER COLUMN workflow_version SET NOT NULL,
  ALTER COLUMN policy_version SET DEFAULT '3.0',
  ALTER COLUMN policy_version SET NOT NULL;

ALTER TABLE workflow_runs
  ALTER COLUMN workflow_version SET DEFAULT '3.0.0',
  ALTER COLUMN policy_version SET DEFAULT '3.0';

UPDATE workflow_runs
SET workflow_version = COALESCE(workflow_version, 'legacy-unversioned'),
    policy_version = COALESCE(policy_version, 'legacy-unversioned')
WHERE workflow_version IS NULL OR policy_version IS NULL;

ALTER TABLE workflow_runs
  ALTER COLUMN workflow_version SET NOT NULL,
  ALTER COLUMN policy_version SET NOT NULL;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'workflow_requests_version_nonempty'
  ) THEN
    ALTER TABLE workflow_requests ADD CONSTRAINT workflow_requests_version_nonempty
      CHECK (btrim(workflow_version) <> '' AND btrim(policy_version) <> '');
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'workflow_runs_version_nonempty'
  ) THEN
    ALTER TABLE workflow_runs ADD CONSTRAINT workflow_runs_version_nonempty
      CHECK (btrim(workflow_version) <> '' AND btrim(policy_version) <> '');
  END IF;
END;
$block$;

CREATE OR REPLACE FUNCTION guard_workflow_run_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.workflow_id IS DISTINCT FROM OLD.workflow_id
     OR NEW.workflow_version IS DISTINCT FROM OLD.workflow_version
     OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.input_hash IS DISTINCT FROM OLD.input_hash THEN
    RAISE EXCEPTION 'workflow identity and version binding are immutable'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS workflow_runs_identity_immutable ON workflow_runs;
CREATE TRIGGER workflow_runs_identity_immutable
  BEFORE UPDATE OF workflow_id,workflow_version,policy_version,idempotency_key,input_hash
  ON workflow_runs
  FOR EACH ROW EXECUTE FUNCTION guard_workflow_run_identity();

CREATE OR REPLACE FUNCTION guard_document_workflow_versions()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  request_workflow_version TEXT;
  request_policy_version TEXT;
  run_workflow_version TEXT;
  run_policy_version TEXT;
BEGIN
  IF NEW.workflow_request_id IS NULL THEN
    RETURN NEW;
  END IF;
  SELECT workflow_version,policy_version
    INTO request_workflow_version,request_policy_version
    FROM workflow_requests WHERE id=NEW.workflow_request_id;
  IF NOT FOUND
     OR request_workflow_version IS DISTINCT FROM '3.0.0'
     OR request_policy_version IS DISTINCT FROM '3.0' THEN
    RAISE EXCEPTION 'document workflow request has incompatible version semantics'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.workflow_run_id IS NOT NULL THEN
    SELECT workflow_version,policy_version
      INTO run_workflow_version,run_policy_version
      FROM workflow_runs WHERE id=NEW.workflow_run_id;
    IF NOT FOUND
       OR run_workflow_version IS DISTINCT FROM request_workflow_version
       OR run_policy_version IS DISTINCT FROM request_policy_version THEN
      RAISE EXCEPTION 'document workflow request/run version mismatch'
        USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS document_extractions_workflow_versions ON document_extractions;
CREATE TRIGGER document_extractions_workflow_versions
  BEFORE INSERT OR UPDATE OF workflow_request_id,workflow_run_id
  ON document_extractions
  FOR EACH ROW EXECUTE FUNCTION guard_document_workflow_versions();

COMMIT;
