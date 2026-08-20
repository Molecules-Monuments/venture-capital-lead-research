-- SPDX-License-Identifier: Apache-2.0
-- Venture Capital Lead Research System 3.0
-- Recovery retry for a reconciled failed workflow run, and the canonical
-- argument digest that makes a replay check payload-sensitive.
--
-- Part 2 (workflow_runs.input_digest) closes a separate gap found by the same
-- audit. workflow-start was invoked with only --workflow, --lead-id and
-- --idempotency-key, so input_hash covered the run's lineage but none of the
-- workflow's actual arguments: two evidence-record runs with completely
-- different evidence_json payloads recorded the SAME input_hash.
-- docs/WORKFLOWS.md promises "Same key plus changed arguments ... fails
-- closed"; that outcome was really being produced by the terminal-state check,
-- which is a weaker and less specific guarantee. input_digest is the sha256 of
-- the runner's canonical argument payload, is immutable after insert, and is
-- what the pre-flight replay probe compares before any mutation runs.
--
-- docs/WORKFLOWS.md tells an operator to "reconcile the same run rather than
-- creating a replacement key" and then to perform "a controlled retry", and the
-- README says to "reuse a key only to recover that same operation". Neither was
-- possible: 'failed' is terminal in guard_workflow_run_transition, and
-- workflow_runs is UNIQUE (workflow_id, idempotency_key), so the first failure
-- permanently poisoned the key. The only way forward was a new key — which
-- discards the idempotency protection exactly when a partially-applied
-- operation makes it matter most.
--
-- This migration adds one governed edge, failed -> queued, reachable only
-- through retry_workflow_run(). The trigger admits it only when the same
-- statement also increments attempt and clears the previous attempt's terminal
-- bookkeeping, so an ordinary transition_workflow_run() call still cannot
-- resurrect a terminal run. input_hash stays immutable
-- (guard_workflow_run_identity, migration 008), so a retry can never smuggle in
-- a different payload: a changed payload still fails closed at workflow-start.
--
-- succeeded, cancelled, and lost remain terminal with no edge out. A run whose
-- cancellation was requested is refused even when it later failed, so a
-- deliberate operator cancellation cannot be undone by a retry.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

ALTER TABLE workflow_runs
  ADD COLUMN IF NOT EXISTS attempt INTEGER NOT NULL DEFAULT 1;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'workflow_runs_attempt_positive'
  ) THEN
    ALTER TABLE workflow_runs ADD CONSTRAINT workflow_runs_attempt_positive
      CHECK (attempt >= 1);
  END IF;
END;
$block$;

COMMENT ON COLUMN workflow_runs.attempt IS
  'Recovery attempt counter. 1 for a run that has never been retried; incremented only by retry_workflow_run().';

-- Nullable: rows written before this migration have no recorded digest, and a
-- run opened by a direct helper call outside the fixed runner does not carry
-- one either. The runner always supplies it, and the probe treats a missing
-- digest as "cannot prove this replay is unchanged" rather than as a match.
ALTER TABLE workflow_runs
  ADD COLUMN IF NOT EXISTS input_digest TEXT;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'workflow_runs_input_digest_shape'
  ) THEN
    ALTER TABLE workflow_runs ADD CONSTRAINT workflow_runs_input_digest_shape
      CHECK (input_digest IS NULL OR input_digest ~ '^[0-9a-f]{64}$');
  END IF;
END;
$block$;

COMMENT ON COLUMN workflow_runs.input_digest IS
  'sha256 of the fixed runner canonical argument payload for this run. Immutable after insert.';

-- Extends the migration 008 identity binding: the argument digest is part of
-- the run identity, so a retry cannot reopen a run under a different payload.
CREATE OR REPLACE FUNCTION guard_workflow_run_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
BEGIN
  IF NEW.workflow_id IS DISTINCT FROM OLD.workflow_id
     OR NEW.workflow_version IS DISTINCT FROM OLD.workflow_version
     OR NEW.policy_version IS DISTINCT FROM OLD.policy_version
     OR NEW.idempotency_key IS DISTINCT FROM OLD.idempotency_key
     OR NEW.input_hash IS DISTINCT FROM OLD.input_hash
     OR NEW.input_digest IS DISTINCT FROM OLD.input_digest THEN
    RAISE EXCEPTION 'workflow identity and version binding are immutable'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$function$;

DROP TRIGGER IF EXISTS workflow_runs_identity_immutable ON workflow_runs;
CREATE TRIGGER workflow_runs_identity_immutable
  BEFORE UPDATE OF workflow_id,workflow_version,policy_version,idempotency_key,input_hash,input_digest
  ON workflow_runs
  FOR EACH ROW EXECUTE FUNCTION guard_workflow_run_identity();

-- Replaces the migration 001 body. Everything above the retry branch is
-- unchanged; keep this function and vcops.RUN_TRANSITIONS in exact parity.
CREATE OR REPLACE FUNCTION guard_workflow_run_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  allowed BOOLEAN := false;
BEGIN
  IF NEW.flow_revision < OLD.flow_revision THEN
    RAISE EXCEPTION 'flow_revision cannot decrease (run_id=%)', OLD.run_id
      USING ERRCODE = '40001';
  END IF;

  IF OLD.cancel_requested_at IS NOT NULL
     AND NEW.status <> OLD.status
     AND NEW.status NOT IN ('cancelled', 'failed', 'lost') THEN
    RAISE EXCEPTION 'cancel-requested workflow cannot advance to % (run_id=%)', NEW.status, OLD.run_id
      USING ERRCODE = '23514';
  END IF;

  IF NEW.status = OLD.status THEN
    allowed := true;
  ELSIF OLD.status = 'queued' AND NEW.status IN ('started', 'running', 'failed', 'cancelled', 'lost') THEN
    allowed := true;
  ELSIF OLD.status = 'started' AND NEW.status IN ('running', 'waiting', 'blocked', 'succeeded', 'failed', 'cancelled', 'lost') THEN
    allowed := true;
  ELSIF OLD.status = 'running' AND NEW.status IN ('waiting', 'blocked', 'succeeded', 'failed', 'cancelled', 'lost') THEN
    allowed := true;
  ELSIF OLD.status = 'waiting' AND NEW.status IN ('running', 'blocked', 'succeeded', 'failed', 'cancelled', 'lost') THEN
    allowed := true;
  ELSIF OLD.status = 'blocked' AND NEW.status IN ('running', 'waiting', 'failed', 'cancelled', 'lost') THEN
    allowed := true;
  -- Recovery retry. Bound to the full reset performed by retry_workflow_run()
  -- so that no other writer can reach it: a transition that merely relabels the
  -- status leaves attempt, finished_at, and error_class untouched and is
  -- refused below exactly as before.
  ELSIF OLD.status = 'failed' AND NEW.status = 'queued'
        AND NEW.attempt = OLD.attempt + 1
        AND NEW.finished_at IS NULL
        AND NEW.error_class IS NULL THEN
    allowed := true;
  END IF;

  IF NOT allowed THEN
    RAISE EXCEPTION 'invalid workflow transition % -> % (run_id=%)', OLD.status, NEW.status, OLD.run_id
      USING ERRCODE = '23514';
  END IF;

  IF NEW.status = 'cancelled' AND NEW.cancel_requested_at IS NULL THEN
    NEW.cancel_requested_at := clock_timestamp();
  END IF;
  IF NEW.status IN ('succeeded', 'failed', 'cancelled', 'lost') AND NEW.finished_at IS NULL THEN
    NEW.finished_at := clock_timestamp();
  END IF;
  IF NEW.status IN ('started', 'running') AND NEW.started_at IS NULL THEN
    NEW.started_at := clock_timestamp();
  END IF;
  IF NEW.status = 'running' THEN
    NEW.heartbeat_at := COALESCE(NEW.heartbeat_at, clock_timestamp());
  END IF;

  NEW.record_version := OLD.record_version + 1;
  NEW.updated_at := clock_timestamp();
  RETURN NEW;
END;
$function$;

-- Reopens exactly one reconciled failure for a fresh attempt under the caller's
-- optimistic revision check. Identity (workflow_id, idempotency_key,
-- input_hash) is untouched, so the reopened run is the same claim; only the
-- previous attempt's outcome is cleared.
CREATE OR REPLACE FUNCTION retry_workflow_run(
  p_run_id TEXT,
  p_expected_record_version BIGINT,
  p_actor_id TEXT DEFAULT 'vcops',
  p_reason TEXT DEFAULT NULL
)
RETURNS SETOF workflow_runs
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
DECLARE
  prior workflow_runs%ROWTYPE;
  changed workflow_runs%ROWTYPE;
BEGIN
  SELECT * INTO prior FROM workflow_runs WHERE run_id = p_run_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'workflow run not found: %', p_run_id USING ERRCODE = 'P0002';
  END IF;
  IF prior.record_version <> p_expected_record_version THEN
    RAISE EXCEPTION 'workflow record version conflict: expected %, actual %',
      p_expected_record_version, prior.record_version USING ERRCODE = '40001';
  END IF;
  IF prior.status <> 'failed' THEN
    RAISE EXCEPTION 'only a failed workflow run can be retried (run_id=%, status=%)',
      p_run_id, prior.status USING ERRCODE = '55000';
  END IF;
  IF prior.cancel_requested_at IS NOT NULL THEN
    RAISE EXCEPTION 'a cancel-requested workflow run cannot be retried (run_id=%)', p_run_id
      USING ERRCODE = '55000';
  END IF;

  UPDATE workflow_runs
  SET status = 'queued',
      attempt = prior.attempt + 1,
      started_at = NULL,
      heartbeat_at = NULL,
      finished_at = NULL,
      error_class = NULL,
      error_message = NULL,
      waiting_reason = NULL,
      blocked_reason = NULL,
      result = '{}'::jsonb
  WHERE id = prior.id
  RETURNING * INTO changed;

  INSERT INTO audit_events (
    event_type, actor_id, actor_type, workflow_run_id, entity_table, entity_id,
    before_state, after_state, details
  ) VALUES (
    'workflow.retry', p_actor_id, 'service', changed.id, 'workflow_runs', changed.id::text,
    jsonb_build_object(
      'status', prior.status, 'attempt', prior.attempt,
      'record_version', prior.record_version,
      'error_class', prior.error_class, 'error_message', prior.error_message
    ),
    jsonb_build_object(
      'status', changed.status, 'attempt', changed.attempt,
      'record_version', changed.record_version
    ),
    jsonb_build_object('reason', p_reason)
  );

  RETURN NEXT changed;
END;
$function$;

REVOKE ALL ON FUNCTION retry_workflow_run(TEXT, BIGINT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION retry_workflow_run(TEXT, BIGINT, TEXT, TEXT) TO openclaw_runtime;

COMMIT;
