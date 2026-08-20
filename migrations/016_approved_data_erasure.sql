-- SPDX-License-Identifier: Apache-2.0
-- Venture Capital Lead Research System 3.0
-- Approved product-data erasure. Closes two gaps at once: product-data
-- retention/erasure (subject request, legal hold expiry) had no executor, and
-- the reviewed consume_approval function had no caller performing a governed
-- mutation atomically. This SECURITY DEFINER function consumes a scoped,
-- one-time approval AND erases a lead's evidence in the SAME transaction.
-- Because the schema is append-only with ON DELETE RESTRICT, erasure is by
-- supersession/tombstone (facts retracted, lead archived), never raw DELETE.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

CREATE OR REPLACE FUNCTION consume_approval_and_erase_lead(
  p_lead_id BIGINT,
  p_token_hash TEXT,
  p_scope_hash TEXT,
  p_action_type TEXT,
  p_target_system TEXT,
  p_payload_hash TEXT,
  p_governed_transaction_id TEXT,
  p_actor_id TEXT
)
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
DECLARE
  lead_row leads%ROWTYPE;
  consumed approvals%ROWTYPE;
  retracted INTEGER := 0;
BEGIN
  IF p_action_type <> 'data.erase_lead' THEN
    RAISE EXCEPTION 'erasure requires an approval scoped to action data.erase_lead' USING ERRCODE = '28000';
  END IF;

  -- Atomic one-time approval consumption (fails closed on invalid/expired/
  -- scope-mismatched approval). Same transaction as the erasure below.
  SELECT * INTO consumed FROM consume_approval(
    p_token_hash, p_scope_hash, p_action_type, p_target_system, p_payload_hash,
    p_governed_transaction_id, p_actor_id
  );

  -- Server-side approval-to-lead binding: the consumed approval's own stored
  -- scope (whose hash was verified above) must name exactly the lead being
  -- erased, and the approval's lead_id column, when set, must agree. Without
  -- this, a caller holding a valid approval for one lead could pass a
  -- different p_lead_id and erase it. The helper enforces the same rule
  -- client-side; the database is the authority.
  IF consumed.scope->>'lead_id' IS NULL
     OR consumed.scope->>'lead_id' <> p_lead_id::text THEN
    RAISE EXCEPTION 'approval scope is not bound to lead %', p_lead_id USING ERRCODE = '28000';
  END IF;
  IF consumed.lead_id IS NOT NULL AND consumed.lead_id <> p_lead_id THEN
    RAISE EXCEPTION 'approval lead binding does not match lead %', p_lead_id USING ERRCODE = '28000';
  END IF;

  SELECT * INTO lead_row FROM leads WHERE id = p_lead_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'lead % does not exist', p_lead_id USING ERRCODE = 'P0002';
  END IF;

  -- Retract every current (non-superseded) fact for the lead by inserting a
  -- superseding retracted row. Every live status is erased — the only status
  -- excluded is 'retracted' itself (already a tombstone), so contradicted,
  -- stale, and unknown facts are retracted too. Append-only preserved; nothing
  -- is deleted.
  WITH current_facts AS (
    SELECT f.* FROM facts f
    WHERE f.lead_id = p_lead_id
      AND f.fact_status <> 'retracted'
      AND NOT EXISTS (SELECT 1 FROM facts s WHERE s.supersedes_fact_id = f.id)
  ), inserted AS (
    INSERT INTO facts (
      company_id, lead_id, workflow_run_id, fact_type, definition, definition_version,
      value_kind, original_value, value_text, value_numeric, value_boolean, value_date,
      value_json, unit, currency_code, period_start, period_end, period_granularity,
      cohort, measurement_basis, fact_status, confidence, observed_at, source_date,
      valid_from, valid_to, supersedes_fact_id, version, created_by, metadata, claim_hash
    )
    SELECT
      company_id, lead_id, NULL, fact_type, definition, definition_version,
      value_kind, original_value, value_text, value_numeric, value_boolean, value_date,
      value_json, unit, currency_code, period_start, period_end, period_granularity,
      cohort, measurement_basis, 'retracted', confidence, observed_at, source_date,
      valid_from, valid_to, id, version + 1, p_actor_id,
      jsonb_build_object('erased', true, 'governed_transaction_id', p_governed_transaction_id), claim_hash
    FROM current_facts
    RETURNING 1
  )
  SELECT count(*) INTO retracted FROM inserted;

  UPDATE leads SET status = 'archived' WHERE id = p_lead_id;

  INSERT INTO audit_events (
    event_type, actor_id, actor_type, transaction_id, entity_table, entity_id,
    before_state, after_state, details
  ) VALUES (
    'data.erasure', p_actor_id, 'operator', p_governed_transaction_id, 'leads', p_lead_id::text,
    jsonb_build_object('status', lead_row.status),
    jsonb_build_object('status', 'archived'),
    jsonb_build_object('retracted_facts', retracted)
  );

  RETURN jsonb_build_object('lead_id', p_lead_id, 'retracted_facts', retracted, 'lead_status', 'archived');
END;
$function$;

REVOKE ALL ON FUNCTION consume_approval_and_erase_lead(
  BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION consume_approval_and_erase_lead(
  BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO openclaw_runtime;

COMMIT;
