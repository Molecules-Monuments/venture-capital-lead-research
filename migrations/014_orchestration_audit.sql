-- OpenClaw Lead Research System 3.0
-- Persist the orchestration/delegation audit trail. The chief's pre-spawn
-- delegation_eval, post-return return_assessment, and terminal chief output
-- lived only in ephemeral model context; this makes "which specialists were
-- consulted for company X, what did each return, why accepted/discarded" a
-- durable, queryable record correlated with the native Task Flow handles.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

CREATE TABLE IF NOT EXISTS orchestration_audit (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  record_kind TEXT NOT NULL CHECK (record_kind IN (
    'delegation_eval', 'return_assessment', 'chief_output'
  )),
  specialist_agent TEXT CHECK (specialist_agent IS NULL OR btrim(specialist_agent) <> ''),
  -- Native OpenClaw Task Flow correlation handles (snapshot, not authority).
  flow_id TEXT,
  flow_revision BIGINT CHECK (flow_revision IS NULL OR flow_revision >= 0),
  task_id TEXT,
  payload JSONB NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  created_by TEXT NOT NULL CHECK (btrim(created_by) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  -- A delegation_eval/return_assessment names a specialist; a chief_output does not.
  CHECK (record_kind = 'chief_output' OR specialist_agent IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS orchestration_audit_lead_idx
  ON orchestration_audit (lead_id, created_at DESC);
CREATE INDEX IF NOT EXISTS orchestration_audit_run_idx
  ON orchestration_audit (workflow_run_id) WHERE workflow_run_id IS NOT NULL;

-- Append-only, like the other domain-history tables (migration 004 helper).
DROP TRIGGER IF EXISTS orchestration_audit_append_only ON orchestration_audit;
CREATE TRIGGER orchestration_audit_append_only
  BEFORE UPDATE OR DELETE ON orchestration_audit
  FOR EACH ROW EXECUTE FUNCTION prevent_domain_history_mutation();

-- Lineage: the run, when supplied, must belong to the same lead.
CREATE OR REPLACE FUNCTION guard_orchestration_audit_lineage()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  run_lead BIGINT;
BEGIN
  IF NEW.workflow_run_id IS NOT NULL THEN
    SELECT lead_id INTO run_lead FROM workflow_runs WHERE id = NEW.workflow_run_id;
    IF run_lead IS NOT NULL AND run_lead IS DISTINCT FROM NEW.lead_id THEN
      RAISE EXCEPTION 'orchestration audit run/lead lineage mismatch' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS orchestration_audit_lineage ON orchestration_audit;
CREATE TRIGGER orchestration_audit_lineage
  BEFORE INSERT ON orchestration_audit
  FOR EACH ROW EXECUTE FUNCTION guard_orchestration_audit_lineage();

REVOKE ALL ON orchestration_audit FROM PUBLIC;
GRANT SELECT, INSERT ON orchestration_audit TO openclaw_runtime;
GRANT USAGE, SELECT ON SEQUENCE orchestration_audit_id_seq TO openclaw_runtime;

COMMIT;
