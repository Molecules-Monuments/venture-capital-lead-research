-- OpenClaw Lead Research System 3.0
-- Extend the workflow-run scope exemption to the reviewed lead/company-free fixed workflows.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

-- The original anonymous constraint (001_initial_v2.sql) exempts only
-- 'system.%' workflow ids from the lead-or-company requirement, which makes
-- the reviewed lead/company-free workflows (preference-observe,
-- preference-forget, document-ingest) violate it at workflow-start.
-- Replace it with a named constraint whose exemption is the closed set of
-- reviewed lead/company-free workflow ids. The new predicate is strictly
-- weaker than the old one, so existing rows always revalidate.
DO $block$
DECLARE
  legacy_definition TEXT;
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'public.workflow_runs'::regclass
      AND conname = 'workflow_runs_scope_check'
  ) THEN
    RETURN;
  END IF;
  SELECT pg_get_constraintdef(oid) INTO legacy_definition
  FROM pg_constraint
  WHERE conrelid = 'public.workflow_runs'::regclass
    AND conname = 'workflow_runs_check';
  IF legacy_definition IS NULL THEN
    RAISE EXCEPTION 'workflow_runs_check is absent; refusing to reconcile the scope constraint';
  END IF;
  IF legacy_definition NOT LIKE '%lead_id IS NOT NULL%'
     OR legacy_definition NOT LIKE '%company_id IS NOT NULL%'
     OR legacy_definition NOT LIKE '%system.%' THEN
    RAISE EXCEPTION 'workflow_runs_check has an unexpected definition: %', legacy_definition;
  END IF;
  ALTER TABLE workflow_runs DROP CONSTRAINT workflow_runs_check;
  ALTER TABLE workflow_runs ADD CONSTRAINT workflow_runs_scope_check CHECK (
    lead_id IS NOT NULL
    OR company_id IS NOT NULL
    OR workflow_id LIKE 'system.%'
    OR workflow_id IN ('preference-observe', 'preference-forget', 'document-ingest')
  );
END;
$block$;

COMMIT;
