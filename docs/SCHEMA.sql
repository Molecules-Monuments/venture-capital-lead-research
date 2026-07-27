-- SPDX-License-Identifier: 0BSD
-- OpenClaw Lead Research System 3.0 — consolidated schema reference (DOCUMENTATION)
--
-- This file is NOT a migration and is applied by nothing: migrate.sh only reads
-- migrations/NNN_*.sql, and this file lives under docs/. It is a schema-only
-- snapshot of the database after migrations/000_roles.sh (roles) and the sixteen
-- forward migrations 001-016 are applied in order, provided as a single-file view
-- so the whole schema can be read and audited in one place.
--
-- The authoritative, reviewed source of the schema is the migrations/ directory.
-- This snapshot is generated from it and can lag if the migrations change; it is
-- documentation, not the source of truth.
--
-- Ownership note: objects are dumped with --no-owner. In a real deployment the
-- owner is openclaw_owner and the least-privilege application role is
-- openclaw_runtime (see migrations/000_roles.sh and docs/DATA_MODEL.md); the
-- GRANT/REVOKE statements below show that runtime privilege model.
--
-- Regenerate (from the package dir, with local PostgreSQL client tools):
--   the run_g4.py disposable-Postgres harness applies the full migration set to a
--   throwaway cluster; pg_dump --schema-only --no-owner that database into here.
--

--
-- PostgreSQL database dump
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_trgm; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

--
-- Name: EXTENSION pg_trgm; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_trgm IS 'text similarity measurement and index searching based on trigrams';

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: notification_outbox; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_outbox (
    id bigint NOT NULL,
    idempotency_key text NOT NULL,
    dedupe_key text NOT NULL,
    provider text NOT NULL,
    provider_account_id text NOT NULL,
    destination_id text NOT NULL,
    lead_id bigint,
    company_id bigint,
    workflow_run_id bigint,
    approval_id bigint,
    severity text NOT NULL,
    urgent_category text,
    status text DEFAULT 'draft'::text NOT NULL,
    subject text NOT NULL,
    body_hash text NOT NULL,
    payload jsonb DEFAULT '{}'::jsonb NOT NULL,
    timezone text DEFAULT 'Europe/Berlin'::text NOT NULL,
    policy_version text NOT NULL,
    deliver_after timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    max_attempts integer DEFAULT 5 NOT NULL,
    attempt_count integer DEFAULT 0 NOT NULL,
    claim_id text,
    claimed_by text,
    claimed_at timestamp with time zone,
    lease_expires_at timestamp with time zone,
    next_attempt_at timestamp with time zone,
    last_error_class text,
    last_error_message text,
    provider_message_id text,
    sent_at timestamp with time zone,
    cancelled_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    request_hash text,
    CONSTRAINT notification_outbox_attempt_count_check CHECK ((attempt_count >= 0)),
    CONSTRAINT notification_outbox_body_hash_check CHECK ((body_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT notification_outbox_check CHECK (((severity <> 'urgent'::text) OR (urgent_category IS NOT NULL))),
    CONSTRAINT notification_outbox_check1 CHECK (((severity <> 'silent_log'::text) OR (provider = 'internal_log'::text))),
    CONSTRAINT notification_outbox_check2 CHECK ((attempt_count <= max_attempts)),
    CONSTRAINT notification_outbox_check3 CHECK (((status <> 'dispatching'::text) OR ((claim_id IS NOT NULL) AND (claimed_by IS NOT NULL) AND (lease_expires_at IS NOT NULL)))),
    CONSTRAINT notification_outbox_check4 CHECK (((status <> 'sent'::text) OR ((provider_message_id IS NOT NULL) AND (sent_at IS NOT NULL)))),
    CONSTRAINT notification_outbox_check5 CHECK (((status <> 'cancelled'::text) OR (cancelled_at IS NOT NULL))),
    CONSTRAINT notification_outbox_dedupe_key_check CHECK ((btrim(dedupe_key) <> ''::text)),
    CONSTRAINT notification_outbox_destination_id_check CHECK ((btrim(destination_id) <> ''::text)),
    CONSTRAINT notification_outbox_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT notification_outbox_max_attempts_check CHECK (((max_attempts >= 1) AND (max_attempts <= 20))),
    CONSTRAINT notification_outbox_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT notification_outbox_provider_account_id_check CHECK ((btrim(provider_account_id) <> ''::text)),
    CONSTRAINT notification_outbox_provider_check CHECK ((provider = ANY (ARRAY['slack'::text, 'msteams'::text, 'discord'::text, 'telegram'::text, 'internal_log'::text]))),
    CONSTRAINT notification_outbox_request_hash_check CHECK (((request_hash IS NULL) OR (request_hash ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT notification_outbox_severity_check CHECK ((severity = ANY (ARRAY['silent_log'::text, 'batched'::text, 'normal'::text, 'urgent'::text]))),
    CONSTRAINT notification_outbox_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'queued'::text, 'held'::text, 'dispatching'::text, 'retry'::text, 'sent'::text, 'failed'::text, 'cancelled'::text, 'logged'::text]))),
    CONSTRAINT notification_outbox_subject_check CHECK ((btrim(subject) <> ''::text)),
    CONSTRAINT notification_outbox_urgent_category_check CHECK (((urgent_category IS NULL) OR (urgent_category = ANY (ARRAY['security_incident'::text, 'data_exposure'::text, 'production_blocker'::text, 'partner_review_blocker'::text, 'approval_expiring'::text]))))
);

--
-- Name: cancel_notification(bigint, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.cancel_notification(p_outbox_id bigint, p_actor_id text) RETURNS SETOF public.notification_outbox
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  changed notification_outbox%ROWTYPE;
BEGIN
  IF p_actor_id IS NULL OR btrim(p_actor_id) = '' THEN
    RAISE EXCEPTION 'actor id is required' USING ERRCODE = '22023';
  END IF;
  UPDATE notification_outbox
  SET status = 'cancelled', cancelled_at = clock_timestamp()
  WHERE id = p_outbox_id
    AND status IN ('draft', 'queued', 'held', 'retry')
  RETURNING * INTO changed;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'notification cannot be cancelled from its current state'
      USING ERRCODE = '40001';
  END IF;
  INSERT INTO audit_events (
    event_type, actor_id, actor_type, workflow_run_id, entity_table, entity_id,
    after_state
  ) VALUES (
    'notification.cancelled', p_actor_id, 'service', changed.workflow_run_id,
    'notification_outbox', changed.id::text, jsonb_build_object('status', changed.status)
  );
  RETURN NEXT changed;
END;
$$;

--
-- Name: claim_notification(text, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.claim_notification(p_worker_id text, p_lease_seconds integer DEFAULT 60) RETURNS SETOF public.notification_outbox
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  candidate_id BIGINT;
  changed notification_outbox%ROWTYPE;
BEGIN
  IF p_worker_id IS NULL OR btrim(p_worker_id) = '' THEN
    RAISE EXCEPTION 'worker id is required' USING ERRCODE = '22023';
  END IF;
  IF p_lease_seconds < 10 OR p_lease_seconds > 900 THEN
    RAISE EXCEPTION 'lease must be between 10 and 900 seconds' USING ERRCODE = '22023';
  END IF;

  -- Recover worker crashes before selecting new work. An exhausted delivery
  -- is terminal; otherwise the abandoned attempt returns to the retry queue.
  UPDATE notification_attempts AS attempt
  SET status = 'abandoned',
      error_class = 'claim_lease_expired',
      error_message = 'dispatcher claim expired before a result was recorded',
      finished_at = clock_timestamp()
  FROM notification_outbox AS outbox
  WHERE attempt.outbox_id = outbox.id
    AND attempt.attempt_number = outbox.attempt_count
    AND attempt.claim_id = outbox.claim_id
    AND attempt.status = 'started'
    AND outbox.status = 'dispatching'
    AND outbox.lease_expires_at <= clock_timestamp();

  UPDATE notification_outbox
  SET status = CASE WHEN attempt_count >= max_attempts THEN 'failed' ELSE 'retry' END,
      next_attempt_at = CASE
        WHEN attempt_count >= max_attempts THEN NULL
        ELSE clock_timestamp()
      END,
      last_error_class = 'claim_lease_expired',
      last_error_message = 'dispatcher claim expired before a result was recorded',
      claim_id = NULL,
      claimed_by = NULL,
      claimed_at = NULL,
      lease_expires_at = NULL
  WHERE status = 'dispatching'
    AND lease_expires_at <= clock_timestamp();

  SELECT id INTO candidate_id
  FROM notification_outbox
  WHERE status IN ('queued', 'retry')
    AND deliver_after <= clock_timestamp()
    AND COALESCE(next_attempt_at, deliver_after) <= clock_timestamp()
    AND attempt_count < max_attempts
  ORDER BY COALESCE(next_attempt_at, deliver_after), id
  FOR UPDATE SKIP LOCKED
  LIMIT 1;

  IF candidate_id IS NULL THEN
    RETURN;
  END IF;

  UPDATE notification_outbox
  SET status = 'dispatching',
      attempt_count = attempt_count + 1,
      claim_id = md5(random()::text || clock_timestamp()::text || candidate_id::text),
      claimed_by = p_worker_id,
      claimed_at = clock_timestamp(),
      lease_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds),
      next_attempt_at = NULL
  WHERE id = candidate_id
  RETURNING * INTO changed;

  INSERT INTO notification_attempts (
    outbox_id, attempt_number, claim_id, status
  ) VALUES (
    changed.id, changed.attempt_count, changed.claim_id, 'started'
  );

  RETURN NEXT changed;
END;
$$;

--
-- Name: approvals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.approvals (
    id bigint NOT NULL,
    request_id text NOT NULL,
    idempotency_key text NOT NULL,
    token_hash text NOT NULL,
    scope_hash text NOT NULL,
    scope jsonb NOT NULL,
    action_preview jsonb NOT NULL,
    action_type text NOT NULL,
    target_system text NOT NULL,
    target_tenant_id text,
    target_channel_id text,
    lead_id bigint,
    company_id bigint,
    workflow_run_id bigint,
    payload_hash text NOT NULL,
    quantitative_limits jsonb DEFAULT '{}'::jsonb NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    requested_by text NOT NULL,
    approver_id text,
    approval_channel_id text,
    decision_note text,
    requested_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    issued_at timestamp with time zone,
    expires_at timestamp with time zone NOT NULL,
    consumed_at timestamp with time zone,
    governed_transaction_id text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT approvals_action_preview_check CHECK ((jsonb_typeof(action_preview) = 'object'::text)),
    CONSTRAINT approvals_action_type_check CHECK ((btrim(action_type) <> ''::text)),
    CONSTRAINT approvals_check CHECK ((expires_at > requested_at)),
    CONSTRAINT approvals_check1 CHECK (((issued_at IS NULL) OR (expires_at > issued_at))),
    CONSTRAINT approvals_check2 CHECK (((status <> ALL (ARRAY['approved'::text, 'consumed'::text])) OR ((approver_id IS NOT NULL) AND (approval_channel_id IS NOT NULL) AND (issued_at IS NOT NULL)))),
    CONSTRAINT approvals_check3 CHECK (((status <> 'consumed'::text) OR ((consumed_at IS NOT NULL) AND (governed_transaction_id IS NOT NULL)))),
    CONSTRAINT approvals_check4 CHECK (((consumed_at IS NULL) OR (consumed_at < expires_at))),
    CONSTRAINT approvals_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT approvals_payload_hash_check CHECK ((payload_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT approvals_quantitative_limits_check CHECK ((jsonb_typeof(quantitative_limits) = 'object'::text)),
    CONSTRAINT approvals_request_id_check CHECK ((btrim(request_id) <> ''::text)),
    CONSTRAINT approvals_requested_by_check CHECK ((btrim(requested_by) <> ''::text)),
    CONSTRAINT approvals_scope_check CHECK ((jsonb_typeof(scope) = 'object'::text)),
    CONSTRAINT approvals_scope_hash_check CHECK ((scope_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT approvals_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'approved'::text, 'rejected'::text, 'revoked'::text, 'expired'::text, 'consumed'::text]))),
    CONSTRAINT approvals_target_system_check CHECK ((btrim(target_system) <> ''::text)),
    CONSTRAINT approvals_token_hash_check CHECK ((token_hash ~ '^[0-9a-f]{64}$'::text))
);

--
-- Name: consume_approval(text, text, text, text, text, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.consume_approval(p_token_hash text, p_scope_hash text, p_action_type text, p_target_system text, p_payload_hash text, p_governed_transaction_id text, p_actor_id text) RETURNS SETOF public.approvals
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  prior approvals%ROWTYPE;
  changed approvals%ROWTYPE;
BEGIN
  SELECT * INTO prior FROM approvals WHERE token_hash = p_token_hash FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'approval token is invalid' USING ERRCODE = '28000';
  END IF;
  IF prior.status <> 'approved' THEN
    RAISE EXCEPTION 'approval is not consumable (status=%)', prior.status USING ERRCODE = '28000';
  END IF;
  IF clock_timestamp() < prior.issued_at OR clock_timestamp() >= prior.expires_at THEN
    RAISE EXCEPTION 'approval is outside its validity window' USING ERRCODE = '28000';
  END IF;
  IF prior.scope_hash <> p_scope_hash
     OR prior.action_type <> p_action_type
     OR prior.target_system <> p_target_system
     OR prior.payload_hash <> p_payload_hash THEN
    RAISE EXCEPTION 'approval scope does not match governed action' USING ERRCODE = '28000';
  END IF;
  IF p_governed_transaction_id IS NULL OR btrim(p_governed_transaction_id) = '' THEN
    RAISE EXCEPTION 'governed transaction id is required' USING ERRCODE = '22023';
  END IF;

  UPDATE approvals
  SET status = 'consumed',
      consumed_at = clock_timestamp(),
      governed_transaction_id = p_governed_transaction_id
  WHERE id = prior.id
  RETURNING * INTO changed;

  INSERT INTO audit_events (
    event_type, actor_id, actor_type, transaction_id, workflow_run_id,
    entity_table, entity_id, before_state, after_state
  ) VALUES (
    'approval.consumed', p_actor_id, 'service', p_governed_transaction_id,
    changed.workflow_run_id, 'approvals', changed.id::text,
    jsonb_build_object('status', prior.status),
    jsonb_build_object('status', changed.status, 'consumed_at', changed.consumed_at)
  );

  RETURN NEXT changed;
END;
$$;

--
-- Name: consume_approval_and_erase_lead(bigint, text, text, text, text, text, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.consume_approval_and_erase_lead(p_lead_id bigint, p_token_hash text, p_scope_hash text, p_action_type text, p_target_system text, p_payload_hash text, p_governed_transaction_id text, p_actor_id text) RETURNS jsonb
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
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
$$;

--
-- Name: decide_approval(text, text, text, text, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.decide_approval(p_request_id text, p_decision text, p_approver_id text, p_approval_channel_id text, p_note text, p_actor_id text) RETURNS SETOF public.approvals
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  prior approvals%ROWTYPE;
  changed approvals%ROWTYPE;
BEGIN
  IF p_decision NOT IN ('approved', 'rejected') THEN
    RAISE EXCEPTION 'decision must be approved or rejected' USING ERRCODE = '22023';
  END IF;
  IF p_approver_id IS NULL OR btrim(p_approver_id) = ''
     OR p_approval_channel_id IS NULL OR btrim(p_approval_channel_id) = ''
     OR p_actor_id IS NULL OR btrim(p_actor_id) = '' THEN
    RAISE EXCEPTION 'stable approver, channel and actor ids are required' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO prior FROM approvals WHERE request_id = p_request_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'approval request not found: %', p_request_id USING ERRCODE = 'P0002';
  END IF;
  IF prior.status <> 'pending' THEN
    RAISE EXCEPTION 'approval request is no longer pending (status=%)', prior.status
      USING ERRCODE = '40001';
  END IF;
  IF clock_timestamp() >= prior.expires_at THEN
    RAISE EXCEPTION 'approval request has expired' USING ERRCODE = '28000';
  END IF;

  UPDATE approvals
  SET status = p_decision,
      approver_id = p_approver_id,
      approval_channel_id = p_approval_channel_id,
      decision_note = p_note,
      issued_at = CASE WHEN p_decision = 'approved' THEN clock_timestamp() ELSE NULL END
  WHERE id = prior.id
  RETURNING * INTO changed;

  INSERT INTO audit_events (
    event_type, actor_id, actor_type, workflow_run_id, entity_table, entity_id,
    before_state, after_state
  ) VALUES (
    'approval.decided', p_actor_id, 'operator', changed.workflow_run_id,
    'approvals', changed.id::text,
    jsonb_build_object('status', prior.status),
    jsonb_build_object('status', changed.status, 'approver_id', changed.approver_id,
      'approval_channel_id', changed.approval_channel_id)
  );

  RETURN NEXT changed;
END;
$$;

--
-- Name: proposals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.proposals (
    id bigint NOT NULL,
    proposal_kind text NOT NULL,
    title text NOT NULL,
    summary text NOT NULL,
    lead_id bigint,
    status text DEFAULT 'submitted'::text NOT NULL,
    content jsonb NOT NULL,
    reviewed_by text,
    reviewed_at timestamp with time zone,
    review_note text,
    supersedes_proposal_id bigint,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT proposals_check CHECK (((supersedes_proposal_id IS NULL) OR (supersedes_proposal_id <> id))),
    CONSTRAINT proposals_check1 CHECK (((status <> ALL (ARRAY['accepted'::text, 'rejected'::text])) OR ((reviewed_by IS NOT NULL) AND (reviewed_at IS NOT NULL)))),
    CONSTRAINT proposals_content_check CHECK ((jsonb_typeof(content) = 'object'::text)),
    CONSTRAINT proposals_created_by_check CHECK ((btrim(created_by) <> ''::text)),
    CONSTRAINT proposals_proposal_kind_check CHECK ((proposal_kind = ANY (ARRAY['schema_change'::text, 'source_policy'::text, 'skill_candidate'::text, 'other'::text]))),
    CONSTRAINT proposals_status_check CHECK ((status = ANY (ARRAY['submitted'::text, 'under_review'::text, 'accepted'::text, 'rejected'::text, 'superseded'::text]))),
    CONSTRAINT proposals_summary_check CHECK ((btrim(summary) <> ''::text)),
    CONSTRAINT proposals_title_check CHECK ((btrim(title) <> ''::text))
);

--
-- Name: decide_proposal(bigint, text, text, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.decide_proposal(p_proposal_id bigint, p_decision text, p_reviewed_by text, p_review_note text, p_actor_id text) RETURNS SETOF public.proposals
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  prior proposals%ROWTYPE;
  changed proposals%ROWTYPE;
BEGIN
  IF p_decision NOT IN ('accepted', 'rejected') THEN
    RAISE EXCEPTION 'decision must be accepted or rejected' USING ERRCODE = '22023';
  END IF;
  IF p_reviewed_by IS NULL OR btrim(p_reviewed_by) = ''
     OR p_actor_id IS NULL OR btrim(p_actor_id) = '' THEN
    RAISE EXCEPTION 'stable reviewer and actor ids are required' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO prior FROM proposals WHERE id = p_proposal_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'proposal not found: %', p_proposal_id USING ERRCODE = 'P0002';
  END IF;
  IF prior.status NOT IN ('submitted', 'under_review') THEN
    RAISE EXCEPTION 'proposal is no longer decidable (status=%)', prior.status
      USING ERRCODE = '40001';
  END IF;

  UPDATE proposals
  SET status = p_decision,
      reviewed_by = p_reviewed_by,
      reviewed_at = clock_timestamp(),
      review_note = p_review_note
  WHERE id = prior.id
  RETURNING * INTO changed;

  INSERT INTO audit_events (
    event_type, actor_id, actor_type, entity_table, entity_id,
    before_state, after_state
  ) VALUES (
    'proposal.decided', p_actor_id, 'operator', 'proposals', changed.id::text,
    jsonb_build_object('status', prior.status),
    jsonb_build_object('status', changed.status, 'reviewed_by', changed.reviewed_by)
  );

  RETURN NEXT changed;
END;
$$;

--
-- Name: finish_notification_attempt(bigint, text, text, text, text, text, text, text, integer); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.finish_notification_attempt(p_outbox_id bigint, p_claim_id text, p_outcome text, p_provider_request_id text DEFAULT NULL::text, p_provider_response_code text DEFAULT NULL::text, p_provider_message_id text DEFAULT NULL::text, p_error_class text DEFAULT NULL::text, p_error_message text DEFAULT NULL::text, p_retry_after_seconds integer DEFAULT NULL::integer) RETURNS SETOF public.notification_outbox
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  current_row notification_outbox%ROWTYPE;
  target_status TEXT;
  changed notification_outbox%ROWTYPE;
BEGIN
  IF p_outcome NOT IN ('succeeded', 'retryable_failure', 'permanent_failure') THEN
    RAISE EXCEPTION 'invalid notification outcome: %', p_outcome USING ERRCODE = '22023';
  END IF;
  IF p_retry_after_seconds IS NOT NULL
     AND (p_retry_after_seconds < 0 OR p_retry_after_seconds > 86400) THEN
    RAISE EXCEPTION 'retry delay must be between 0 and 86400 seconds'
      USING ERRCODE = '22023';
  END IF;

  SELECT * INTO current_row
  FROM notification_outbox
  WHERE id = p_outbox_id
  FOR UPDATE;

  IF NOT FOUND OR current_row.status <> 'dispatching' OR current_row.claim_id <> p_claim_id THEN
    RAISE EXCEPTION 'notification claim is invalid or stale' USING ERRCODE = '40001';
  END IF;
  IF current_row.lease_expires_at <= clock_timestamp() THEN
    RAISE EXCEPTION 'notification claim lease expired' USING ERRCODE = '40001';
  END IF;

  IF p_outcome = 'succeeded' THEN
    IF p_provider_message_id IS NULL OR btrim(p_provider_message_id) = '' THEN
      RAISE EXCEPTION 'provider message id is required for success' USING ERRCODE = '22023';
    END IF;
    target_status := 'sent';
  ELSIF p_outcome = 'retryable_failure' AND current_row.attempt_count < current_row.max_attempts THEN
    IF p_error_class IS NULL THEN
      RAISE EXCEPTION 'error class is required for failure' USING ERRCODE = '22023';
    END IF;
    target_status := 'retry';
  ELSE
    IF p_error_class IS NULL THEN
      RAISE EXCEPTION 'error class is required for failure' USING ERRCODE = '22023';
    END IF;
    target_status := 'failed';
  END IF;

  UPDATE notification_attempts
  SET status = p_outcome,
      provider_request_id = p_provider_request_id,
      provider_response_code = p_provider_response_code,
      provider_message_id = p_provider_message_id,
      error_class = p_error_class,
      error_message = p_error_message,
      finished_at = clock_timestamp()
  WHERE outbox_id = current_row.id
    AND attempt_number = current_row.attempt_count
    AND claim_id = p_claim_id
    AND status = 'started';

  IF NOT FOUND THEN
    RAISE EXCEPTION 'notification attempt row is missing or already finished' USING ERRCODE = '40001';
  END IF;

  UPDATE notification_outbox
  SET status = target_status,
      provider_message_id = CASE WHEN target_status = 'sent' THEN p_provider_message_id ELSE provider_message_id END,
      sent_at = CASE WHEN target_status = 'sent' THEN clock_timestamp() ELSE sent_at END,
      next_attempt_at = CASE
        WHEN target_status = 'retry' THEN clock_timestamp() + make_interval(
          secs => COALESCE(p_retry_after_seconds, LEAST(3600, 30 * (2 ^ GREATEST(attempt_count - 1, 0))::INTEGER))
        )
        ELSE NULL
      END,
      last_error_class = p_error_class,
      last_error_message = p_error_message,
      claim_id = NULL,
      claimed_by = NULL,
      claimed_at = NULL,
      lease_expires_at = NULL
  WHERE id = current_row.id
  RETURNING * INTO changed;

  RETURN NEXT changed;
END;
$$;

--
-- Name: guard_approval_transition(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_approval_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
DECLARE
  allowed BOOLEAN := false;
BEGIN
  IF TG_OP = 'INSERT' THEN
    IF session_user = 'openclaw_runtime'
       AND (NEW.status <> 'pending'
       OR NEW.approver_id IS NOT NULL
       OR NEW.issued_at IS NOT NULL
       OR NEW.consumed_at IS NOT NULL
       OR NEW.governed_transaction_id IS NOT NULL) THEN
      RAISE EXCEPTION 'new approval must begin pending and unissued'
        USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
  END IF;

  -- Scope and token identity are immutable after request creation.
  IF NEW.token_hash <> OLD.token_hash
     OR NEW.scope_hash <> OLD.scope_hash
     OR NEW.scope <> OLD.scope
     OR NEW.action_preview <> OLD.action_preview
     OR NEW.action_type <> OLD.action_type
     OR NEW.target_system <> OLD.target_system
     OR NEW.payload_hash <> OLD.payload_hash THEN
    RAISE EXCEPTION 'approval token, scope, action, target and payload are immutable'
      USING ERRCODE = '23514';
  END IF;

  IF NEW.status = OLD.status THEN
    allowed := true;
  ELSIF OLD.status = 'pending' AND NEW.status IN ('approved', 'rejected', 'revoked', 'expired') THEN
    allowed := true;
  ELSIF OLD.status = 'approved' AND NEW.status IN ('consumed', 'revoked', 'expired') THEN
    allowed := true;
  END IF;

  IF NOT allowed THEN
    RAISE EXCEPTION 'invalid approval transition % -> % (approval_id=%)', OLD.status, NEW.status, OLD.id
      USING ERRCODE = '23514';
  END IF;

  NEW.updated_at := clock_timestamp();
  RETURN NEW;
END;
$$;

--
-- Name: guard_compiled_truth_fact(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_compiled_truth_fact() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_compiled_truth_lineage(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_compiled_truth_lineage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_document_workflow_request(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_document_workflow_request() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_document_workflow_versions(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_document_workflow_versions() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_evaluation_lineage(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_evaluation_lineage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_fact_lineage(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_fact_lineage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_initial_notification(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_initial_notification() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  IF session_user <> 'openclaw_runtime' THEN
    RETURN NEW;
  END IF;
  IF NEW.status NOT IN ('draft', 'queued', 'held', 'logged') THEN
    RAISE EXCEPTION 'new notification must begin draft, queued, held, or logged'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.status = 'logged' AND NEW.provider <> 'internal_log' THEN
    RAISE EXCEPTION 'logged notification requires internal_log provider'
      USING ERRCODE = '23514';
  END IF;
  IF NEW.attempt_count <> 0
     OR NEW.claim_id IS NOT NULL
     OR NEW.provider_message_id IS NOT NULL
     OR NEW.sent_at IS NOT NULL THEN
    RAISE EXCEPTION 'new notification cannot contain delivery state'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

--
-- Name: guard_initial_workflow_run(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_initial_workflow_run() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  -- The owner may restore historical rows; the application role must use the
  -- live lifecycle from its initial state.
  IF session_user <> 'openclaw_runtime' THEN
    RETURN NEW;
  END IF;
  IF NEW.status NOT IN ('queued', 'started') THEN
    RAISE EXCEPTION 'new workflow run must begin queued or started'
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$$;

--
-- Name: guard_memo_citation_lineage(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_memo_citation_lineage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_memo_lineage(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_memo_lineage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_orchestration_audit_lineage(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_orchestration_audit_lineage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_proposal_decision(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_proposal_decision() RETURNS trigger
    LANGUAGE plpgsql
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  proposals_owner TEXT;
  is_owner BOOLEAN;
BEGIN
  SELECT tableowner INTO proposals_owner
  FROM pg_catalog.pg_tables
  WHERE schemaname = 'public' AND tablename = 'proposals';
  is_owner := pg_has_role(current_user, proposals_owner, 'USAGE');
  IF TG_OP = 'INSERT' THEN
    -- A proposal must be born undecided: without this branch the runtime
    -- role could INSERT a row already 'accepted' with a forged reviewed_by,
    -- bypassing decide_proposal and its audit event entirely (the same
    -- forgery the approvals guard blocks on INSERT).
    IF NEW.status NOT IN ('submitted', 'under_review') AND NOT is_owner THEN
      RAISE EXCEPTION 'proposals must be created undecided; decisions pass only through decide_proposal'
        USING ERRCODE = '28000';
    END IF;
    RETURN NEW;
  END IF;
  IF OLD.status IN ('accepted', 'rejected') AND NOT is_owner THEN
    RAISE EXCEPTION 'decided proposals are immutable' USING ERRCODE = '28000';
  END IF;
  IF NEW.status IN ('accepted', 'rejected')
     AND OLD.status NOT IN ('accepted', 'rejected')
     AND NOT is_owner THEN
    RAISE EXCEPTION 'proposal decisions are operator-lane; use decide_proposal'
      USING ERRCODE = '28000';
  END IF;
  RETURN NEW;
END;
$$;

--
-- Name: guard_workflow_lineage(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_workflow_lineage() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_workflow_run_identity(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_workflow_run_identity() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: guard_workflow_run_transition(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.guard_workflow_run_transition() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
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
$$;

--
-- Name: prevent_audit_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_audit_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = '55000';
END;
$$;

--
-- Name: prevent_domain_history_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_domain_history_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION '% is append-only; create a superseding/versioned row', TG_TABLE_NAME
    USING ERRCODE = '55000';
END;
$$;

--
-- Name: prevent_migration_record_mutation(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.prevent_migration_record_mutation() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  RAISE EXCEPTION 'schema_migrations is append-only; checksum mismatches fail closed'
    USING ERRCODE = '55000';
END;
$$;

--
-- Name: facts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.facts (
    id bigint NOT NULL,
    company_id bigint NOT NULL,
    lead_id bigint,
    workflow_run_id bigint,
    fact_type text NOT NULL,
    definition text NOT NULL,
    definition_version text DEFAULT '1'::text NOT NULL,
    value_kind text NOT NULL,
    original_value text,
    value_text text,
    value_numeric numeric,
    value_boolean boolean,
    value_date date,
    value_json jsonb,
    unit text,
    currency_code text,
    period_start date,
    period_end date,
    period_granularity text,
    cohort text,
    measurement_basis text,
    fact_status text DEFAULT 'submitted_claim'::text NOT NULL,
    confidence numeric(4,3) DEFAULT 0.000 NOT NULL,
    observed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    source_date date,
    valid_from date,
    valid_to date,
    supersedes_fact_id bigint,
    version integer DEFAULT 1 NOT NULL,
    created_by text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    claim_hash text,
    CONSTRAINT facts_check CHECK (((period_end IS NULL) OR (period_start IS NULL) OR (period_end >= period_start))),
    CONSTRAINT facts_check1 CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT facts_check2 CHECK (((supersedes_fact_id IS NULL) OR (supersedes_fact_id <> id))),
    CONSTRAINT facts_check3 CHECK ((((value_kind = 'text'::text) AND (value_text IS NOT NULL) AND (value_numeric IS NULL) AND (value_boolean IS NULL) AND (value_date IS NULL) AND (value_json IS NULL)) OR ((value_kind = 'numeric'::text) AND (value_text IS NULL) AND (value_numeric IS NOT NULL) AND (value_boolean IS NULL) AND (value_date IS NULL) AND (value_json IS NULL)) OR ((value_kind = 'boolean'::text) AND (value_text IS NULL) AND (value_numeric IS NULL) AND (value_boolean IS NOT NULL) AND (value_date IS NULL) AND (value_json IS NULL)) OR ((value_kind = 'date'::text) AND (value_text IS NULL) AND (value_numeric IS NULL) AND (value_boolean IS NULL) AND (value_date IS NOT NULL) AND (value_json IS NULL)) OR ((value_kind = 'json'::text) AND (value_text IS NULL) AND (value_numeric IS NULL) AND (value_boolean IS NULL) AND (value_date IS NULL) AND (value_json IS NOT NULL)) OR ((value_kind = 'unknown'::text) AND (value_text IS NULL) AND (value_numeric IS NULL) AND (value_boolean IS NULL) AND (value_date IS NULL) AND (value_json IS NULL)))),
    CONSTRAINT facts_claim_hash_check CHECK (((claim_hash IS NULL) OR (claim_hash ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT facts_confidence_check CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT facts_created_by_check CHECK ((btrim(created_by) <> ''::text)),
    CONSTRAINT facts_currency_code_check CHECK (((currency_code IS NULL) OR (currency_code ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT facts_definition_check CHECK ((btrim(definition) <> ''::text)),
    CONSTRAINT facts_fact_status_check CHECK ((fact_status = ANY (ARRAY['submitted_claim'::text, 'verified_fact'::text, 'derived_inference'::text, 'contradicted'::text, 'stale'::text, 'retracted'::text, 'unknown'::text]))),
    CONSTRAINT facts_fact_type_check CHECK ((btrim(fact_type) <> ''::text)),
    CONSTRAINT facts_metadata_check CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT facts_period_granularity_check CHECK (((period_granularity IS NULL) OR (period_granularity = ANY (ARRAY['instant'::text, 'day'::text, 'week'::text, 'month'::text, 'quarter'::text, 'year'::text, 'lifetime'::text, 'unknown'::text])))),
    CONSTRAINT facts_value_kind_check CHECK ((value_kind = ANY (ARRAY['text'::text, 'numeric'::text, 'boolean'::text, 'date'::text, 'json'::text, 'unknown'::text]))),
    CONSTRAINT facts_version_check CHECK ((version > 0))
);

--
-- Name: promote_submitted_claim(bigint, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.promote_submitted_claim(p_fact_id bigint, p_actor text DEFAULT 'vcops'::text) RETURNS SETOF public.facts
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  claim facts%ROWTYPE;
  policy fact_promotion_policy%ROWTYPE;
  superseding_id BIGINT;
  independent_sources INTEGER;
  qualifying_single INTEGER;
  promoted facts%ROWTYPE;
BEGIN
  IF p_actor IS NULL OR btrim(p_actor) = '' THEN
    RAISE EXCEPTION 'promotion requires an actor identity' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO claim FROM facts WHERE id = p_fact_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'fact % does not exist', p_fact_id USING ERRCODE = 'P0002';
  END IF;
  IF claim.fact_status <> 'submitted_claim' THEN
    RAISE EXCEPTION 'only submitted_claim facts are promotable (fact_id=%, status=%)',
      p_fact_id, claim.fact_status USING ERRCODE = '23514';
  END IF;
  SELECT id INTO superseding_id FROM facts WHERE supersedes_fact_id = p_fact_id LIMIT 1;
  IF superseding_id IS NOT NULL THEN
    RAISE EXCEPTION 'fact % is already superseded by fact %', p_fact_id, superseding_id
      USING ERRCODE = '23514';
  END IF;
  SELECT * INTO policy FROM fact_promotion_policy WHERE id = 1;
  IF NOT FOUND OR NOT policy.auto_promote THEN
    RETURN;
  END IF;

  -- Independence keying:
  --   * Web/URI sources corroborate ONLY by verified content identity
  --     (sources.content_sha256, the hash of the fetched page bytes the steward
  --     records). A bare model-supplied URL with no content hash contributes no
  --     independent key (the CASE yields NULL, which count(DISTINCT) ignores),
  --     and two URLs that returned identical content collapse to one. This closes
  --     the "two distinct model-chosen hosts auto-promote a claim" gap: recording
  --     the same claim twice from two invented hosts no longer corroborates.
  --   * Non-URI sources are already content-addressed (document artifacts carry
  --     stable_source_id 'artifact:<sha>') or provider-identified; a source that
  --     fits neither collapses into one shared 'unclassified' key so it can never
  --     multiply independence.
  -- The remaining residual — content is still model-supplied, so a boundary that
  -- fetches the URL itself is the full tamper-proof closure (CR-001 part 6) — is
  -- backstopped by the human evaluate-lead approval gate on the compiled-truth
  -- snapshot before any verified_fact reaches a memo or score.
  SELECT
    count(DISTINCT
      CASE
        WHEN s.canonical_uri ~ '^https?://' THEN
          CASE WHEN s.content_sha256 IS NOT NULL THEN 'web-content:' || s.content_sha256 END
        ELSE
          COALESCE(
            s.provider || ':' || COALESCE(s.provider_account_id, '') || ':' || s.stable_source_id,
            'unclassified'
          )
      END
    ),
    count(*) FILTER (WHERE s.source_kind = ANY (policy.single_source_kinds))
    INTO independent_sources, qualifying_single
  FROM fact_sources fs
  JOIN sources s ON s.id = fs.source_id
  WHERE fs.fact_id = p_fact_id
    AND fs.evidence_role IN ('primary', 'supporting')
    AND NOT (s.trust_level = ANY (policy.excluded_trust_levels));

  IF independent_sources < policy.min_independent_sources AND qualifying_single = 0 THEN
    RETURN;
  END IF;

  INSERT INTO facts (
    company_id, lead_id, workflow_run_id, fact_type, definition, definition_version,
    value_kind, original_value, value_text, value_numeric, value_boolean, value_date,
    value_json, unit, currency_code, period_start, period_end, period_granularity,
    cohort, measurement_basis, fact_status, confidence, observed_at, source_date,
    valid_from, valid_to, supersedes_fact_id, version, created_by, metadata, claim_hash
  )
  SELECT
    company_id, lead_id, workflow_run_id, fact_type, definition, definition_version,
    value_kind, original_value, value_text, value_numeric, value_boolean, value_date,
    value_json, unit, currency_code, period_start, period_end, period_granularity,
    cohort, measurement_basis, 'verified_fact', confidence, observed_at, source_date,
    valid_from, valid_to, id, version + 1, p_actor, metadata, claim_hash
  FROM facts
  WHERE id = p_fact_id
  RETURNING * INTO promoted;

  INSERT INTO fact_sources (
    fact_id, source_id, artifact_id, extraction_id, evidence_role,
    citation_label, source_locator, quoted_text_hash
  )
  SELECT
    promoted.id, source_id, artifact_id, extraction_id, evidence_role,
    citation_label, source_locator, quoted_text_hash
  FROM fact_sources
  WHERE fact_id = p_fact_id
  ON CONFLICT DO NOTHING;

  INSERT INTO audit_events (
    event_type, actor_id, actor_type, workflow_run_id, entity_table, entity_id,
    before_state, after_state, details
  )
  VALUES (
    'fact.promoted', p_actor, 'service', claim.workflow_run_id, 'facts', promoted.id::text,
    jsonb_build_object('fact_id', claim.id, 'fact_status', claim.fact_status),
    jsonb_build_object('fact_id', promoted.id, 'fact_status', promoted.fact_status,
                       'supersedes_fact_id', promoted.supersedes_fact_id),
    jsonb_build_object('independent_sources', independent_sources,
                       'qualifying_single_sources', qualifying_single,
                       'min_independent_sources', policy.min_independent_sources)
  );

  RETURN NEXT promoted;
  RETURN;
END;
$$;

--
-- Name: register_schema_migration(text, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.register_schema_migration(p_version text, p_name text, p_checksum_sha256 text) RETURNS void
    LANGUAGE plpgsql
    AS $_$
DECLARE
  stored_name TEXT;
  stored_checksum TEXT;
BEGIN
  IF p_version IS NULL OR btrim(p_version) = '' OR p_name IS NULL OR btrim(p_name) = '' THEN
    RAISE EXCEPTION 'migration version and name are required' USING ERRCODE = '22023';
  END IF;
  IF p_checksum_sha256 IS NULL OR p_checksum_sha256 !~ '^[0-9a-f]{64}$' THEN
    RAISE EXCEPTION 'migration checksum must be a lowercase SHA-256 digest' USING ERRCODE = '22023';
  END IF;

  SELECT name, checksum_sha256
    INTO stored_name, stored_checksum
  FROM schema_migrations
  WHERE version = p_version
  FOR UPDATE;

  IF FOUND THEN
    IF stored_name <> p_name OR stored_checksum <> p_checksum_sha256 THEN
      RAISE EXCEPTION 'migration % checksum/name mismatch', p_version USING ERRCODE = '55000';
    END IF;
    RETURN;
  END IF;

  INSERT INTO schema_migrations (version, name, checksum_sha256)
  VALUES (p_version, p_name, p_checksum_sha256);
END;
$_$;

--
-- Name: registrable_host(text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.registrable_host(p_host text) RETURNS text
    LANGUAGE plpgsql IMMUTABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  labels TEXT[];
  n INTEGER;
  last_two TEXT;
BEGIN
  IF p_host IS NULL OR btrim(p_host) = '' THEN
    RETURN NULL;
  END IF;
  labels := string_to_array(lower(btrim(p_host)), '.');
  n := array_length(labels, 1);
  IF n IS NULL OR n <= 2 THEN
    RETURN lower(btrim(p_host));
  END IF;
  last_two := labels[n - 1] || '.' || labels[n];
  IF last_two IN (
    'co.uk','org.uk','ac.uk','gov.uk','ltd.uk','plc.uk','net.uk','me.uk',
    'com.au','net.au','org.au','edu.au','gov.au','id.au',
    'co.nz','net.nz','org.nz','govt.nz',
    'co.jp','ne.jp','or.jp','ac.jp','go.jp',
    'com.br','net.br','org.br','gov.br',
    'co.in','net.in','org.in','gen.in','firm.in','ind.in',
    'com.cn','net.cn','org.cn','gov.cn',
    'com.sg','net.sg','org.sg','edu.sg','gov.sg',
    'com.hk','net.hk','org.hk','edu.hk','gov.hk',
    'com.mx','net.mx','org.mx',
    'co.za','net.za','org.za','web.za',
    'co.kr','ne.kr','or.kr','re.kr','go.kr',
    'com.tr','net.tr','org.tr','gov.tr',
    'com.tw','net.tw','org.tw',
    'co.il','net.il','org.il','ac.il','gov.il',
    'com.ar','net.ar','org.ar',
    'co.id','net.id','or.id','web.id',
    'com.my','net.my','org.my',
    'com.ua','net.ua','org.ua',
    'co.th','in.th','or.th','ac.th',
    'com.vn','net.vn','org.vn'
  ) THEN
    RETURN labels[n - 2] || '.' || last_two;
  END IF;
  RETURN last_two;
END;
$$;

--
-- Name: release_held_notification(bigint, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.release_held_notification(p_outbox_id bigint, p_actor_id text) RETURNS SETOF public.notification_outbox
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  changed notification_outbox%ROWTYPE;
BEGIN
  IF p_actor_id IS NULL OR btrim(p_actor_id) = '' THEN
    RAISE EXCEPTION 'actor id is required' USING ERRCODE = '22023';
  END IF;
  UPDATE notification_outbox
  SET status = 'queued'
  WHERE id = p_outbox_id
    AND status = 'held'
    AND deliver_after <= clock_timestamp()
  RETURNING * INTO changed;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'held notification is missing, not due, or no longer held'
      USING ERRCODE = '40001';
  END IF;
  INSERT INTO audit_events (
    event_type, actor_id, actor_type, workflow_run_id, entity_table, entity_id,
    after_state
  ) VALUES (
    'notification.released', p_actor_id, 'service', changed.workflow_run_id,
    'notification_outbox', changed.id::text, jsonb_build_object('status', changed.status)
  );
  RETURN NEXT changed;
END;
$$;

--
-- Name: workflow_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_runs (
    id bigint NOT NULL,
    run_id text NOT NULL,
    workflow_id text NOT NULL,
    workflow_version text DEFAULT '3.0.0'::text NOT NULL,
    lead_id bigint,
    company_id bigint,
    parent_run_id bigint,
    external_flow_id text,
    idempotency_key text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    flow_revision bigint DEFAULT 0 NOT NULL,
    record_version bigint DEFAULT 1 NOT NULL,
    input_hash text,
    policy_version text DEFAULT '3.0'::text NOT NULL,
    requested_by text,
    started_at timestamp with time zone,
    heartbeat_at timestamp with time zone,
    waiting_reason text,
    blocked_reason text,
    cancel_requested_at timestamp with time zone,
    cancelled_by text,
    cancellation_reason text,
    finished_at timestamp with time zone,
    error_class text,
    error_message text,
    result jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT workflow_runs_check1 CHECK (((status <> 'cancelled'::text) OR (cancel_requested_at IS NOT NULL))),
    CONSTRAINT workflow_runs_check2 CHECK (((status <> ALL (ARRAY['succeeded'::text, 'failed'::text, 'cancelled'::text, 'lost'::text])) OR (finished_at IS NOT NULL))),
    CONSTRAINT workflow_runs_check3 CHECK (((status <> 'failed'::text) OR (error_class IS NOT NULL))),
    CONSTRAINT workflow_runs_flow_revision_check CHECK ((flow_revision >= 0)),
    CONSTRAINT workflow_runs_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT workflow_runs_input_hash_check CHECK (((input_hash IS NULL) OR (input_hash ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT workflow_runs_record_version_check CHECK ((record_version > 0)),
    CONSTRAINT workflow_runs_result_check CHECK ((jsonb_typeof(result) = 'object'::text)),
    CONSTRAINT workflow_runs_run_id_check CHECK ((btrim(run_id) <> ''::text)),
    CONSTRAINT workflow_runs_scope_check CHECK (((lead_id IS NOT NULL) OR (company_id IS NOT NULL) OR (workflow_id ~~ 'system.%'::text) OR (workflow_id = ANY (ARRAY['preference-observe'::text, 'preference-forget'::text, 'document-ingest'::text])))),
    CONSTRAINT workflow_runs_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'started'::text, 'running'::text, 'waiting'::text, 'blocked'::text, 'succeeded'::text, 'failed'::text, 'cancelled'::text, 'lost'::text]))),
    CONSTRAINT workflow_runs_version_nonempty CHECK (((btrim(workflow_version) <> ''::text) AND (btrim(policy_version) <> ''::text))),
    CONSTRAINT workflow_runs_workflow_id_check CHECK ((btrim(workflow_id) <> ''::text))
);

--
-- Name: request_workflow_cancel(text, bigint, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.request_workflow_cancel(p_run_id text, p_expected_record_version bigint, p_actor_id text, p_reason text) RETURNS SETOF public.workflow_runs
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  prior workflow_runs%ROWTYPE;
  changed workflow_runs%ROWTYPE;
BEGIN
  IF p_actor_id IS NULL OR btrim(p_actor_id) = ''
     OR p_reason IS NULL OR btrim(p_reason) = '' THEN
    RAISE EXCEPTION 'cancellation actor and reason are required' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO prior FROM workflow_runs WHERE run_id = p_run_id FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'workflow run not found: %', p_run_id USING ERRCODE = 'P0002';
  END IF;
  IF prior.record_version <> p_expected_record_version THEN
    RAISE EXCEPTION 'workflow record version conflict: expected %, actual %',
      p_expected_record_version, prior.record_version USING ERRCODE = '40001';
  END IF;
  IF prior.status IN ('succeeded', 'failed', 'cancelled', 'lost') THEN
    RAISE EXCEPTION 'terminal workflow cannot accept cancellation request (status=%)', prior.status
      USING ERRCODE = '40001';
  END IF;
  IF prior.cancel_requested_at IS NOT NULL THEN
    RAISE EXCEPTION 'workflow cancellation was already requested' USING ERRCODE = '40001';
  END IF;

  UPDATE workflow_runs
  SET cancel_requested_at = clock_timestamp(),
      cancelled_by = p_actor_id,
      cancellation_reason = p_reason
  WHERE id = prior.id
  RETURNING * INTO changed;

  INSERT INTO audit_events (
    event_type, actor_id, actor_type, workflow_run_id, entity_table, entity_id,
    before_state, after_state
  ) VALUES (
    'workflow.cancel_requested', p_actor_id, 'service', changed.id,
    'workflow_runs', changed.id::text,
    jsonb_build_object('status', prior.status, 'record_version', prior.record_version),
    jsonb_build_object('status', changed.status, 'record_version', changed.record_version,
      'cancel_requested_at', changed.cancel_requested_at)
  );

  RETURN NEXT changed;
END;
$$;

--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at := clock_timestamp();
  RETURN NEW;
END;
$$;

--
-- Name: signal_source_is_due(text, timestamp with time zone); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.signal_source_is_due(p_cadence text, p_last_scanned_at timestamp with time zone) RETURNS boolean
    LANGUAGE plpgsql STABLE
    SET search_path TO 'pg_catalog', 'public'
    AS $$
DECLARE
  interval_span INTERVAL;
BEGIN
  interval_span := CASE p_cadence
    WHEN 'daily' THEN INTERVAL '1 day'
    WHEN 'weekly' THEN INTERVAL '7 days'
    WHEN 'monthly' THEN INTERVAL '30 days'
  END;
  IF interval_span IS NULL THEN
    RAISE EXCEPTION 'unknown signal source cadence: %', p_cadence USING ERRCODE = '22023';
  END IF;
  RETURN p_last_scanned_at IS NULL OR p_last_scanned_at < now() - interval_span;
END;
$$;

--
-- Name: touch_versioned_row(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.touch_versioned_row() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
  NEW.updated_at := clock_timestamp();
  NEW.row_version := OLD.row_version + 1;
  RETURN NEW;
END;
$$;

--
-- Name: transition_workflow_run(text, bigint, text, bigint, text, jsonb, text, text); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.transition_workflow_run(p_run_id text, p_expected_record_version bigint, p_new_status text, p_flow_revision bigint DEFAULT NULL::bigint, p_actor_id text DEFAULT 'vcops'::text, p_result jsonb DEFAULT NULL::jsonb, p_error_class text DEFAULT NULL::text, p_error_message text DEFAULT NULL::text) RETURNS SETOF public.workflow_runs
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog', 'public'
    AS $$
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

  UPDATE workflow_runs
  SET status = p_new_status,
      flow_revision = COALESCE(p_flow_revision, flow_revision),
      result = COALESCE(p_result, result),
      heartbeat_at = CASE WHEN p_new_status = 'running' THEN clock_timestamp() ELSE heartbeat_at END,
      error_class = COALESCE(p_error_class, error_class),
      error_message = COALESCE(p_error_message, error_message),
      cancelled_by = CASE WHEN p_new_status = 'cancelled' THEN p_actor_id ELSE cancelled_by END
  WHERE id = prior.id
  RETURNING * INTO changed;

  INSERT INTO audit_events (
    event_type, actor_id, actor_type, workflow_run_id, entity_table, entity_id,
    before_state, after_state
  ) VALUES (
    'workflow.transition', p_actor_id, 'service', changed.id, 'workflow_runs', changed.id::text,
    jsonb_build_object('status', prior.status, 'record_version', prior.record_version, 'flow_revision', prior.flow_revision),
    jsonb_build_object('status', changed.status, 'record_version', changed.record_version, 'flow_revision', changed.flow_revision)
  );

  RETURN NEXT changed;
END;
$$;

--
-- Name: approvals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.approvals ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.approvals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: audit_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_events (
    id bigint NOT NULL,
    event_type text NOT NULL,
    actor_id text NOT NULL,
    actor_type text DEFAULT 'service'::text NOT NULL,
    transaction_id text,
    request_id text,
    workflow_run_id bigint,
    entity_table text NOT NULL,
    entity_id text NOT NULL,
    before_state jsonb,
    after_state jsonb,
    details jsonb DEFAULT '{}'::jsonb NOT NULL,
    occurred_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT audit_events_actor_id_check CHECK ((btrim(actor_id) <> ''::text)),
    CONSTRAINT audit_events_actor_type_check CHECK ((actor_type = ANY (ARRAY['operator'::text, 'service'::text, 'agent'::text, 'system'::text]))),
    CONSTRAINT audit_events_details_check CHECK ((jsonb_typeof(details) = 'object'::text)),
    CONSTRAINT audit_events_entity_id_check CHECK ((btrim(entity_id) <> ''::text)),
    CONSTRAINT audit_events_entity_table_check CHECK ((btrim(entity_table) <> ''::text)),
    CONSTRAINT audit_events_event_type_check CHECK ((btrim(event_type) <> ''::text))
);

--
-- Name: audit_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.audit_events ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.audit_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: channel_principals; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.channel_principals (
    id bigint NOT NULL,
    provider text NOT NULL,
    account_id text NOT NULL,
    sender_id text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    last_seen_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT channel_principals_account_id_check CHECK ((btrim(account_id) <> ''::text)),
    CONSTRAINT channel_principals_provider_check CHECK ((provider = ANY (ARRAY['slack'::text, 'msteams'::text, 'discord'::text, 'telegram'::text]))),
    CONSTRAINT channel_principals_sender_id_check CHECK ((btrim(sender_id) <> ''::text))
);

--
-- Name: channel_principals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.channel_principals ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.channel_principals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: companies; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.companies (
    id bigint NOT NULL,
    name text NOT NULL,
    legal_name text,
    canonical_domain text,
    website_uri text,
    sector text,
    geography text,
    stage_estimate text,
    one_line_description text,
    status text DEFAULT 'active'::text NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    row_version bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT companies_canonical_domain_check CHECK (((canonical_domain IS NULL) OR (canonical_domain = lower(btrim(canonical_domain))))),
    CONSTRAINT companies_canonical_domain_check1 CHECK (((canonical_domain IS NULL) OR (canonical_domain !~ '[/@:]'::text))),
    CONSTRAINT companies_metadata_check CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT companies_name_check CHECK ((btrim(name) <> ''::text)),
    CONSTRAINT companies_row_version_check CHECK ((row_version > 0)),
    CONSTRAINT companies_status_check CHECK ((status = ANY (ARRAY['active'::text, 'inactive'::text, 'acquired'::text, 'closed'::text, 'merged'::text, 'unknown'::text])))
);

--
-- Name: companies_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.companies ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.companies_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: company_aliases; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_aliases (
    id bigint NOT NULL,
    company_id bigint NOT NULL,
    alias_kind text DEFAULT 'trade_name'::text NOT NULL,
    alias_value text NOT NULL,
    normalized_alias text NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    confidentiality text DEFAULT 'internal'::text NOT NULL,
    confidence numeric(4,3) DEFAULT 1.000 NOT NULL,
    source_id bigint,
    valid_from date,
    valid_to date,
    created_by text DEFAULT 'migration-006'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT company_aliases_alias_kind_check CHECK ((alias_kind = ANY (ARRAY['canonical_name'::text, 'legal_name'::text, 'trade_name'::text, 'former_name'::text, 'acronym'::text, 'other'::text]))),
    CONSTRAINT company_aliases_alias_value_check CHECK ((btrim(alias_value) <> ''::text)),
    CONSTRAINT company_aliases_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT company_aliases_confidence_check CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT company_aliases_confidentiality_check CHECK ((confidentiality = ANY (ARRAY['public'::text, 'internal'::text, 'confidential'::text, 'restricted'::text]))),
    CONSTRAINT company_aliases_created_by_check CHECK ((btrim(created_by) <> ''::text)),
    CONSTRAINT company_aliases_normalized_alias_check CHECK (((btrim(normalized_alias) = normalized_alias) AND (normalized_alias <> ''::text))),
    CONSTRAINT company_aliases_status_check CHECK ((status = ANY (ARRAY['active'::text, 'deprecated'::text, 'disputed'::text])))
);

--
-- Name: company_aliases_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.company_aliases ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.company_aliases_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: company_domains; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_domains (
    id bigint NOT NULL,
    company_id bigint NOT NULL,
    hostname text NOT NULL,
    domain_kind text DEFAULT 'primary'::text NOT NULL,
    status text DEFAULT 'claimed'::text NOT NULL,
    confidentiality text DEFAULT 'internal'::text NOT NULL,
    confidence numeric(4,3) DEFAULT 1.000 NOT NULL,
    source_id bigint,
    verified_at timestamp with time zone,
    valid_from date,
    valid_to date,
    created_by text DEFAULT 'migration-006'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT company_domains_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT company_domains_check1 CHECK (((status <> 'verified'::text) OR (verified_at IS NOT NULL))),
    CONSTRAINT company_domains_confidence_check CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT company_domains_confidentiality_check CHECK ((confidentiality = ANY (ARRAY['public'::text, 'internal'::text, 'confidential'::text, 'restricted'::text]))),
    CONSTRAINT company_domains_created_by_check CHECK ((btrim(created_by) <> ''::text)),
    CONSTRAINT company_domains_domain_kind_check CHECK ((domain_kind = ANY (ARRAY['primary'::text, 'redirect'::text, 'former'::text, 'product'::text, 'other'::text]))),
    CONSTRAINT company_domains_hostname_check CHECK (((hostname = lower(btrim(hostname))) AND (hostname <> ''::text) AND (hostname !~ '[/@:]'::text))),
    CONSTRAINT company_domains_status_check CHECK ((status = ANY (ARRAY['verified'::text, 'claimed'::text, 'deprecated'::text, 'disputed'::text])))
);

--
-- Name: company_domains_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.company_domains ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.company_domains_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: company_external_ids; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.company_external_ids (
    id bigint NOT NULL,
    company_id bigint NOT NULL,
    provider text NOT NULL,
    provider_account_id text DEFAULT 'default'::text NOT NULL,
    external_id text NOT NULL,
    status text DEFAULT 'verified'::text NOT NULL,
    confidentiality text DEFAULT 'internal'::text NOT NULL,
    confidence numeric(4,3) DEFAULT 1.000 NOT NULL,
    source_id bigint,
    valid_from date,
    valid_to date,
    created_by text DEFAULT 'vcops'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT company_external_ids_check CHECK (((valid_to IS NULL) OR (valid_from IS NULL) OR (valid_to >= valid_from))),
    CONSTRAINT company_external_ids_confidence_check CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT company_external_ids_confidentiality_check CHECK ((confidentiality = ANY (ARRAY['public'::text, 'internal'::text, 'confidential'::text, 'restricted'::text]))),
    CONSTRAINT company_external_ids_created_by_check CHECK ((btrim(created_by) <> ''::text)),
    CONSTRAINT company_external_ids_external_id_check CHECK ((btrim(external_id) <> ''::text)),
    CONSTRAINT company_external_ids_provider_account_id_check CHECK ((btrim(provider_account_id) <> ''::text)),
    CONSTRAINT company_external_ids_provider_check CHECK (((provider = lower(btrim(provider))) AND (provider <> ''::text))),
    CONSTRAINT company_external_ids_status_check CHECK ((status = ANY (ARRAY['verified'::text, 'claimed'::text, 'deprecated'::text, 'disputed'::text])))
);

--
-- Name: company_external_ids_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.company_external_ids ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.company_external_ids_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: compiled_truth; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.compiled_truth (
    id bigint NOT NULL,
    lead_id bigint NOT NULL,
    company_id bigint NOT NULL,
    workflow_run_id bigint,
    prior_snapshot_id bigint,
    snapshot_version integer NOT NULL,
    policy_version text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    current_view jsonb DEFAULT '{}'::jsonb NOT NULL,
    coverage jsonb DEFAULT '{}'::jsonb NOT NULL,
    coverage_percent numeric(5,2) DEFAULT 0 NOT NULL,
    evidence_timeline jsonb DEFAULT '[]'::jsonb NOT NULL,
    missing_data jsonb DEFAULT '[]'::jsonb NOT NULL,
    material_delta jsonb DEFAULT '{}'::jsonb NOT NULL,
    evidence_packet_hash text NOT NULL,
    compiled_by text NOT NULL,
    compiled_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    stale_after timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    fact_history jsonb DEFAULT '[]'::jsonb NOT NULL,
    contradiction_history jsonb DEFAULT '[]'::jsonb NOT NULL,
    trajectory_history jsonb DEFAULT '[]'::jsonb NOT NULL,
    decision_guards jsonb DEFAULT '{"state_complete": false, "identity_reliable": false, "blocking_contradiction": false}'::jsonb NOT NULL,
    CONSTRAINT compiled_truth_check CHECK (((prior_snapshot_id IS NULL) OR (prior_snapshot_id <> id))),
    CONSTRAINT compiled_truth_check1 CHECK (((stale_after IS NULL) OR (stale_after > compiled_at))),
    CONSTRAINT compiled_truth_compiled_by_check CHECK ((btrim(compiled_by) <> ''::text)),
    CONSTRAINT compiled_truth_contradiction_history_check CHECK ((jsonb_typeof(contradiction_history) = 'array'::text)),
    CONSTRAINT compiled_truth_coverage_check CHECK ((jsonb_typeof(coverage) = 'object'::text)),
    CONSTRAINT compiled_truth_coverage_percent_check CHECK (((coverage_percent >= (0)::numeric) AND (coverage_percent <= (100)::numeric))),
    CONSTRAINT compiled_truth_current_view_check CHECK ((jsonb_typeof(current_view) = 'object'::text)),
    CONSTRAINT compiled_truth_decision_guards_check CHECK (((jsonb_typeof(decision_guards) = 'object'::text) AND (jsonb_typeof((decision_guards -> 'state_complete'::text)) = 'boolean'::text) AND (jsonb_typeof((decision_guards -> 'identity_reliable'::text)) = 'boolean'::text) AND (jsonb_typeof((decision_guards -> 'blocking_contradiction'::text)) = 'boolean'::text))),
    CONSTRAINT compiled_truth_evidence_packet_hash_check CHECK ((evidence_packet_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT compiled_truth_evidence_timeline_check CHECK ((jsonb_typeof(evidence_timeline) = 'array'::text)),
    CONSTRAINT compiled_truth_fact_history_check CHECK ((jsonb_typeof(fact_history) = 'array'::text)),
    CONSTRAINT compiled_truth_material_delta_check CHECK ((jsonb_typeof(material_delta) = 'object'::text)),
    CONSTRAINT compiled_truth_missing_data_check CHECK ((jsonb_typeof(missing_data) = 'array'::text)),
    CONSTRAINT compiled_truth_policy_version_check CHECK ((btrim(policy_version) <> ''::text)),
    CONSTRAINT compiled_truth_snapshot_version_check CHECK ((snapshot_version > 0)),
    CONSTRAINT compiled_truth_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'current'::text, 'superseded'::text, 'stale'::text, 'invalid'::text]))),
    CONSTRAINT compiled_truth_trajectory_history_check CHECK ((jsonb_typeof(trajectory_history) = 'array'::text))
);

--
-- Name: compiled_truth_facts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.compiled_truth_facts (
    compiled_truth_id bigint NOT NULL,
    fact_id bigint NOT NULL,
    support_role text NOT NULL,
    claim_path text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT compiled_truth_facts_support_role_check CHECK ((support_role = ANY (ARRAY['current'::text, 'historical'::text, 'contradicted'::text, 'stale'::text, 'missing_context'::text])))
);

--
-- Name: compiled_truth_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.compiled_truth ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.compiled_truth_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: contradiction_facts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contradiction_facts (
    contradiction_id bigint NOT NULL,
    fact_id bigint NOT NULL,
    assertion_role text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT contradiction_facts_assertion_role_check CHECK ((assertion_role = ANY (ARRAY['left'::text, 'right'::text, 'supporting'::text, 'resolution'::text])))
);

--
-- Name: contradictions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.contradictions (
    id bigint NOT NULL,
    lead_id bigint NOT NULL,
    company_id bigint NOT NULL,
    workflow_run_id bigint,
    finding_kind text NOT NULL,
    severity text NOT NULL,
    status text DEFAULT 'open'::text NOT NULL,
    fact_type text NOT NULL,
    definition text NOT NULL,
    normalized_unit text,
    normalized_currency_code text,
    measurement_basis text,
    cohort text,
    overlap_start date,
    overlap_end date,
    normalization jsonb DEFAULT '{}'::jsonb NOT NULL,
    explanation text NOT NULL,
    resolution_note text,
    reviewed_by text,
    reviewed_at timestamp with time zone,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT contradictions_check CHECK (((overlap_end IS NULL) OR (overlap_start IS NULL) OR (overlap_end >= overlap_start))),
    CONSTRAINT contradictions_check1 CHECK (((status <> ALL (ARRAY['resolved'::text, 'accepted_risk'::text, 'dismissed'::text])) OR (reviewed_at IS NOT NULL))),
    CONSTRAINT contradictions_created_by_check CHECK ((btrim(created_by) <> ''::text)),
    CONSTRAINT contradictions_explanation_check CHECK ((btrim(explanation) <> ''::text)),
    CONSTRAINT contradictions_finding_kind_check CHECK ((finding_kind = ANY (ARRAY['contradiction'::text, 'ordinary_change'::text, 'superseded'::text, 'stale'::text, 'not_comparable'::text, 'identity_conflict'::text]))),
    CONSTRAINT contradictions_normalization_check CHECK ((jsonb_typeof(normalization) = 'object'::text)),
    CONSTRAINT contradictions_normalized_currency_code_check CHECK (((normalized_currency_code IS NULL) OR (normalized_currency_code ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT contradictions_severity_check CHECK ((severity = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text, 'blocking'::text]))),
    CONSTRAINT contradictions_status_check CHECK ((status = ANY (ARRAY['open'::text, 'under_review'::text, 'resolved'::text, 'accepted_risk'::text, 'dismissed'::text])))
);

--
-- Name: contradictions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.contradictions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.contradictions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: document_extractions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_extractions (
    id bigint NOT NULL,
    artifact_id bigint NOT NULL,
    workflow_run_id bigint,
    extractor_name text NOT NULL,
    extractor_version text NOT NULL,
    idempotency_key text NOT NULL,
    status text DEFAULT 'queued'::text NOT NULL,
    output_uri text,
    extracted_sha256 text,
    detected_mime_type text,
    page_count integer,
    sheet_count integer,
    row_count bigint,
    character_count bigint,
    contains_formulas boolean DEFAULT false NOT NULL,
    safety_findings jsonb DEFAULT '[]'::jsonb NOT NULL,
    extraction_summary jsonb DEFAULT '{}'::jsonb NOT NULL,
    error_class text,
    error_message text,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    request_hash text,
    workflow_request_id bigint,
    CONSTRAINT document_extractions_character_count_check CHECK (((character_count IS NULL) OR (character_count >= 0))),
    CONSTRAINT document_extractions_check CHECK (((status <> 'succeeded'::text) OR ((output_uri IS NOT NULL) AND (extracted_sha256 IS NOT NULL)))),
    CONSTRAINT document_extractions_check1 CHECK (((status <> 'failed'::text) OR (error_class IS NOT NULL))),
    CONSTRAINT document_extractions_check2 CHECK (((status <> ALL (ARRAY['succeeded'::text, 'failed'::text, 'quarantined'::text, 'unsupported'::text])) OR (finished_at IS NOT NULL))),
    CONSTRAINT document_extractions_extracted_sha256_check CHECK (((extracted_sha256 IS NULL) OR (extracted_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT document_extractions_extraction_summary_check CHECK ((jsonb_typeof(extraction_summary) = 'object'::text)),
    CONSTRAINT document_extractions_extractor_name_check CHECK ((btrim(extractor_name) <> ''::text)),
    CONSTRAINT document_extractions_extractor_version_check CHECK ((btrim(extractor_version) <> ''::text)),
    CONSTRAINT document_extractions_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT document_extractions_page_count_check CHECK (((page_count IS NULL) OR (page_count >= 0))),
    CONSTRAINT document_extractions_request_hash_check CHECK (((request_hash IS NULL) OR (request_hash ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT document_extractions_row_count_check CHECK (((row_count IS NULL) OR (row_count >= 0))),
    CONSTRAINT document_extractions_safety_findings_check CHECK ((jsonb_typeof(safety_findings) = 'array'::text)),
    CONSTRAINT document_extractions_sheet_count_check CHECK (((sheet_count IS NULL) OR (sheet_count >= 0))),
    CONSTRAINT document_extractions_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'running'::text, 'succeeded'::text, 'failed'::text, 'quarantined'::text, 'unsupported'::text])))
);

--
-- Name: document_extractions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.document_extractions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.document_extractions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: document_facts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_facts (
    id bigint NOT NULL,
    extraction_id bigint NOT NULL,
    fact_id bigint NOT NULL,
    page_number integer,
    sheet_name text,
    cell_range text,
    paragraph_number integer,
    source_locator text,
    locator_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT document_facts_locator_metadata_check CHECK ((jsonb_typeof(locator_metadata) = 'object'::text)),
    CONSTRAINT document_facts_page_number_check CHECK (((page_number IS NULL) OR (page_number > 0))),
    CONSTRAINT document_facts_paragraph_number_check CHECK (((paragraph_number IS NULL) OR (paragraph_number > 0)))
);

--
-- Name: document_facts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.document_facts ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.document_facts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: entity_resolution_consumptions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entity_resolution_consumptions (
    id bigint NOT NULL,
    resolution_decision_id uuid NOT NULL,
    company_id bigint NOT NULL,
    outcome text NOT NULL,
    consumed_by text NOT NULL,
    consumed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT entity_resolution_consumptions_consumed_by_check CHECK ((btrim(consumed_by) <> ''::text)),
    CONSTRAINT entity_resolution_consumptions_outcome_check CHECK ((outcome = ANY (ARRAY['linked_existing'::text, 'created_new'::text])))
);

--
-- Name: entity_resolution_consumptions_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.entity_resolution_consumptions ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.entity_resolution_consumptions_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: entity_resolution_decisions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entity_resolution_decisions (
    id uuid NOT NULL,
    resolution_run_id uuid NOT NULL,
    outcome text NOT NULL,
    matched_company_id bigint,
    match_method text,
    match_confidence numeric(4,3),
    candidate_company_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    reasons jsonb DEFAULT '[]'::jsonb NOT NULL,
    policy_version text DEFAULT 'entity-resolution.v1'::text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT entity_resolution_decisions_candidate_company_ids_check CHECK ((jsonb_typeof(candidate_company_ids) = 'array'::text)),
    CONSTRAINT entity_resolution_decisions_check CHECK ((((outcome = 'existing'::text) AND (matched_company_id IS NOT NULL)) OR ((outcome <> 'existing'::text) AND (matched_company_id IS NULL)))),
    CONSTRAINT entity_resolution_decisions_match_confidence_check CHECK (((match_confidence IS NULL) OR ((match_confidence >= (0)::numeric) AND (match_confidence <= (1)::numeric)))),
    CONSTRAINT entity_resolution_decisions_outcome_check CHECK ((outcome = ANY (ARRAY['existing'::text, 'new_allowed'::text, 'human_review'::text, 'no_match'::text, 'denied'::text]))),
    CONSTRAINT entity_resolution_decisions_policy_version_check CHECK ((btrim(policy_version) <> ''::text)),
    CONSTRAINT entity_resolution_decisions_reasons_check CHECK ((jsonb_typeof(reasons) = 'array'::text))
);

--
-- Name: entity_resolution_runs; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.entity_resolution_runs (
    id uuid NOT NULL,
    workflow_request_id bigint,
    requester_id text NOT NULL,
    purpose text NOT NULL,
    max_confidentiality text NOT NULL,
    idempotency_key text NOT NULL,
    query_hash text NOT NULL,
    identity_query jsonb NOT NULL,
    policy_version text DEFAULT 'entity-resolution.v1'::text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT entity_resolution_runs_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT entity_resolution_runs_identity_query_check CHECK ((jsonb_typeof(identity_query) = 'object'::text)),
    CONSTRAINT entity_resolution_runs_max_confidentiality_check CHECK ((max_confidentiality = ANY (ARRAY['public'::text, 'internal'::text, 'confidential'::text, 'restricted'::text]))),
    CONSTRAINT entity_resolution_runs_policy_version_check CHECK ((btrim(policy_version) <> ''::text)),
    CONSTRAINT entity_resolution_runs_purpose_check CHECK ((purpose = ANY (ARRAY['company_creation'::text, 'research'::text, 'qualification'::text, 'memo'::text, 'merge_review'::text, 'compatibility_lookup'::text]))),
    CONSTRAINT entity_resolution_runs_query_hash_check CHECK ((query_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT entity_resolution_runs_requester_id_check CHECK ((btrim(requester_id) <> ''::text))
);

--
-- Name: evaluation_criteria; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluation_criteria (
    evaluation_id bigint NOT NULL,
    criterion_key text NOT NULL,
    criterion_score numeric(3,2) NOT NULL,
    weight_points numeric(5,2) NOT NULL,
    weighted_points numeric(6,3) NOT NULL,
    is_missing boolean DEFAULT false NOT NULL,
    rationale text NOT NULL,
    evidence_fact_ids jsonb DEFAULT '[]'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT evaluation_criteria_check CHECK (((NOT is_missing) OR ((criterion_score = (0)::numeric) AND (weighted_points = (0)::numeric)))),
    CONSTRAINT evaluation_criteria_check1 CHECK ((weighted_points <= weight_points)),
    CONSTRAINT evaluation_criteria_criterion_key_check CHECK ((btrim(criterion_key) <> ''::text)),
    CONSTRAINT evaluation_criteria_criterion_score_check CHECK (((criterion_score >= (0)::numeric) AND (criterion_score <= (5)::numeric))),
    CONSTRAINT evaluation_criteria_evidence_fact_ids_check CHECK ((jsonb_typeof(evidence_fact_ids) = 'array'::text)),
    CONSTRAINT evaluation_criteria_weight_points_check CHECK (((weight_points >= (0)::numeric) AND (weight_points <= (100)::numeric))),
    CONSTRAINT evaluation_criteria_weighted_points_check CHECK (((weighted_points >= (0)::numeric) AND (weighted_points <= (100)::numeric)))
);

--
-- Name: evaluations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evaluations (
    id bigint NOT NULL,
    lead_id bigint NOT NULL,
    workflow_run_id bigint,
    compiled_truth_id bigint NOT NULL,
    evaluation_version integer NOT NULL,
    rubric_version text NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    fixed_denominator numeric(5,2) DEFAULT 100 NOT NULL,
    total_score numeric(6,3) NOT NULL,
    display_score numeric(3,2) NOT NULL,
    recommendation_band text NOT NULL,
    evidence_coverage_percent numeric(5,2) NOT NULL,
    confidence numeric(4,3) NOT NULL,
    missing_criteria jsonb DEFAULT '[]'::jsonb NOT NULL,
    blockers jsonb DEFAULT '[]'::jsonb NOT NULL,
    scoring_details jsonb DEFAULT '{}'::jsonb NOT NULL,
    evidence_packet_hash text NOT NULL,
    evaluated_by text NOT NULL,
    evaluated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    request_hash text,
    CONSTRAINT evaluations_blockers_check CHECK ((jsonb_typeof(blockers) = 'array'::text)),
    CONSTRAINT evaluations_confidence_check CHECK (((confidence >= (0)::numeric) AND (confidence <= (1)::numeric))),
    CONSTRAINT evaluations_display_score_check CHECK (((display_score >= (0)::numeric) AND (display_score <= (5)::numeric))),
    CONSTRAINT evaluations_evaluation_version_check CHECK ((evaluation_version > 0)),
    CONSTRAINT evaluations_evidence_coverage_percent_check CHECK (((evidence_coverage_percent >= (0)::numeric) AND (evidence_coverage_percent <= (100)::numeric))),
    CONSTRAINT evaluations_evidence_packet_hash_check CHECK ((evidence_packet_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT evaluations_fixed_denominator_check CHECK ((fixed_denominator = (100)::numeric)),
    CONSTRAINT evaluations_missing_criteria_check CHECK ((jsonb_typeof(missing_criteria) = 'array'::text)),
    CONSTRAINT evaluations_recommendation_band_check CHECK ((recommendation_band = ANY (ARRAY['pass'::text, 'watch'::text, 'research_deeper'::text, 'high_priority'::text, 'insufficient_evidence'::text, 'needs_human_review'::text]))),
    CONSTRAINT evaluations_request_hash_check CHECK (((request_hash IS NULL) OR (request_hash ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT evaluations_rubric_version_check CHECK ((btrim(rubric_version) <> ''::text)),
    CONSTRAINT evaluations_score_band_check CHECK (((recommendation_band = ANY (ARRAY['insufficient_evidence'::text, 'needs_human_review'::text])) OR ((total_score >= (0)::numeric) AND (total_score < (50)::numeric) AND (recommendation_band = 'pass'::text)) OR ((total_score >= (50)::numeric) AND (total_score < (66)::numeric) AND (recommendation_band = 'watch'::text)) OR ((total_score >= (66)::numeric) AND (total_score < (82)::numeric) AND (recommendation_band = 'research_deeper'::text)) OR ((total_score >= (82)::numeric) AND (total_score <= (100)::numeric) AND (recommendation_band = 'high_priority'::text)) OR ((total_score >= (82)::numeric) AND (total_score <= (100)::numeric) AND (recommendation_band = 'research_deeper'::text) AND ((scoring_details ->> 'override'::text) = 'high_priority_prerequisites_missing'::text)))),
    CONSTRAINT evaluations_scoring_details_check CHECK ((jsonb_typeof(scoring_details) = 'object'::text)),
    CONSTRAINT evaluations_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'final'::text, 'superseded'::text, 'invalid'::text]))),
    CONSTRAINT evaluations_total_score_check CHECK (((total_score >= (0)::numeric) AND (total_score <= (100)::numeric)))
);

--
-- Name: evaluations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.evaluations ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.evaluations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: evidence_artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.evidence_artifacts (
    id bigint NOT NULL,
    sha256 text NOT NULL,
    artifact_type text NOT NULL,
    storage_tier text NOT NULL,
    trust_boundary text NOT NULL,
    confidentiality text DEFAULT 'internal'::text NOT NULL,
    retention_class text DEFAULT 'standard'::text NOT NULL,
    storage_uri text,
    external_uri text,
    mime_type text,
    size_bytes bigint,
    content_encoding text,
    collected_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT evidence_artifacts_artifact_type_check CHECK ((artifact_type = ANY (ARRAY['channel_message'::text, 'document'::text, 'url_capture'::text, 'connector_export'::text, 'memo'::text, 'report'::text, 'internal_note'::text, 'extracted_text'::text, 'structured_data'::text, 'other'::text]))),
    CONSTRAINT evidence_artifacts_check CHECK (((storage_uri IS NOT NULL) OR (external_uri IS NOT NULL) OR (storage_tier = 'postgres_row'::text))),
    CONSTRAINT evidence_artifacts_confidentiality_check CHECK ((confidentiality = ANY (ARRAY['public'::text, 'internal'::text, 'confidential'::text, 'restricted'::text]))),
    CONSTRAINT evidence_artifacts_metadata_check CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT evidence_artifacts_retention_class_check CHECK ((retention_class = ANY (ARRAY['short'::text, 'standard'::text, 'long'::text, 'legal_hold'::text, 'delete_after_review'::text]))),
    CONSTRAINT evidence_artifacts_sha256_check CHECK ((sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT evidence_artifacts_size_bytes_check CHECK (((size_bytes IS NULL) OR (size_bytes >= 0))),
    CONSTRAINT evidence_artifacts_storage_tier_check CHECK ((storage_tier = ANY (ARRAY['workspace_file'::text, 'object_store'::text, 'postgres_row'::text, 'external_reference'::text, 'quarantine'::text]))),
    CONSTRAINT evidence_artifacts_trust_boundary_check CHECK ((trust_boundary = ANY (ARRAY['internal_admin'::text, 'allowlisted_operator'::text, 'remote_channel'::text, 'public_web'::text, 'paid_connector'::text, 'untrusted_upload'::text, 'generated_internal'::text, 'unknown'::text])))
);

--
-- Name: evidence_artifacts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.evidence_artifacts ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.evidence_artifacts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: fact_promotion_policy; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fact_promotion_policy (
    id integer DEFAULT 1 NOT NULL,
    auto_promote boolean DEFAULT true NOT NULL,
    min_independent_sources integer DEFAULT 2 NOT NULL,
    single_source_kinds text[] DEFAULT ARRAY['regulatory_filing'::text] NOT NULL,
    excluded_trust_levels text[] DEFAULT ARRAY['untrusted_upload'::text, 'unknown'::text] NOT NULL,
    official_source_domains text[] DEFAULT ARRAY[]::text[] NOT NULL,
    updated_by text DEFAULT 'migration-012'::text NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT fact_promotion_policy_excluded_trust_levels_check CHECK ((excluded_trust_levels <@ ARRAY['internal_admin'::text, 'allowlisted_operator'::text, 'remote_channel'::text, 'public_web'::text, 'paid_connector'::text, 'untrusted_upload'::text, 'generated_internal'::text, 'unknown'::text])),
    CONSTRAINT fact_promotion_policy_id_check CHECK ((id = 1)),
    CONSTRAINT fact_promotion_policy_min_independent_sources_check CHECK ((min_independent_sources >= 1)),
    CONSTRAINT fact_promotion_policy_single_source_kinds_check CHECK ((single_source_kinds <@ ARRAY['primary_document'::text, 'company_website'::text, 'regulatory_filing'::text, 'channel_message'::text, 'public_web'::text, 'paid_connector'::text, 'operator_statement'::text, 'internal_analysis'::text, 'provider_event'::text, 'other'::text])),
    CONSTRAINT fact_promotion_policy_updated_by_check CHECK ((btrim(updated_by) <> ''::text))
);

--
-- Name: fact_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.fact_sources (
    id bigint NOT NULL,
    fact_id bigint NOT NULL,
    source_id bigint NOT NULL,
    artifact_id bigint,
    extraction_id bigint,
    evidence_role text DEFAULT 'primary'::text NOT NULL,
    citation_label text,
    source_locator text,
    quoted_text_hash text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT fact_sources_check CHECK (((artifact_id IS NOT NULL) OR (extraction_id IS NULL))),
    CONSTRAINT fact_sources_evidence_role_check CHECK ((evidence_role = ANY (ARRAY['primary'::text, 'supporting'::text, 'contradicting'::text, 'context'::text]))),
    CONSTRAINT fact_sources_quoted_text_hash_check CHECK (((quoted_text_hash IS NULL) OR (quoted_text_hash ~ '^[0-9a-f]{64}$'::text)))
);

--
-- Name: fact_sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.fact_sources ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.fact_sources_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: facts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.facts ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.facts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: lead_artifacts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.lead_artifacts (
    id bigint NOT NULL,
    lead_id bigint NOT NULL,
    artifact_id bigint NOT NULL,
    source_id bigint,
    association_role text DEFAULT 'evidence'::text NOT NULL,
    original_filename text,
    source_locator text,
    submitted_by text,
    received_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    provenance jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT lead_artifacts_association_role_check CHECK ((association_role = ANY (ARRAY['submission'::text, 'evidence'::text, 'contradicting_evidence'::text, 'context'::text, 'generated_output'::text]))),
    CONSTRAINT lead_artifacts_provenance_check CHECK ((jsonb_typeof(provenance) = 'object'::text))
);

--
-- Name: lead_artifacts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.lead_artifacts ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.lead_artifacts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: leads; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.leads (
    id bigint NOT NULL,
    company_id bigint,
    lead_title text NOT NULL,
    origin_group text DEFAULT 'unspecified'::text NOT NULL,
    origin_subtype text DEFAULT 'unknown'::text NOT NULL,
    origin_confidence text DEFAULT 'low'::text NOT NULL,
    origin_note text,
    intake_channel text,
    channel_provider text,
    channel_account_id text,
    channel_event_id text,
    channel_message_id text,
    channel_sender_id text,
    channel_permalink text,
    source_trust_level text DEFAULT 'unknown'::text NOT NULL,
    confidentiality text DEFAULT 'internal'::text NOT NULL,
    referrer_name text,
    referrer_organization text,
    submitted_by text,
    owner_id text,
    status text DEFAULT 'new'::text NOT NULL,
    priority text DEFAULT 'unassigned'::text NOT NULL,
    thesis_version text,
    missing_fields jsonb DEFAULT '[]'::jsonb NOT NULL,
    submitted_claims jsonb DEFAULT '{}'::jsonb NOT NULL,
    idempotency_key text NOT NULL,
    row_version bigint DEFAULT 1 NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    request_hash text,
    CONSTRAINT leads_confidentiality_check CHECK ((confidentiality = ANY (ARRAY['public'::text, 'internal'::text, 'confidential'::text, 'restricted'::text]))),
    CONSTRAINT leads_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT leads_lead_title_check CHECK ((btrim(lead_title) <> ''::text)),
    CONSTRAINT leads_missing_fields_check CHECK ((jsonb_typeof(missing_fields) = 'array'::text)),
    CONSTRAINT leads_origin_confidence_check CHECK ((origin_confidence = ANY (ARRAY['low'::text, 'medium'::text, 'high'::text]))),
    CONSTRAINT leads_origin_group_check CHECK ((origin_group = ANY (ARRAY['outbound'::text, 'inbound'::text, 'unspecified'::text]))),
    CONSTRAINT leads_origin_subtype_check CHECK ((btrim(origin_subtype) <> ''::text)),
    CONSTRAINT leads_priority_check CHECK ((priority = ANY (ARRAY['unassigned'::text, 'low'::text, 'medium'::text, 'high'::text, 'urgent'::text]))),
    CONSTRAINT leads_request_hash_check CHECK (((request_hash IS NULL) OR (request_hash ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT leads_row_version_check CHECK ((row_version > 0)),
    CONSTRAINT leads_source_trust_level_check CHECK ((source_trust_level = ANY (ARRAY['internal_admin'::text, 'allowlisted_operator'::text, 'remote_channel'::text, 'public_web'::text, 'paid_connector'::text, 'untrusted_upload'::text, 'generated_internal'::text, 'unknown'::text]))),
    CONSTRAINT leads_status_check CHECK ((status = ANY (ARRAY['new'::text, 'triaged'::text, 'needs_review'::text, 'researching'::text, 'watch'::text, 'passed'::text, 'research_deeper'::text, 'high_priority'::text, 'rejected'::text, 'archived'::text]))),
    CONSTRAINT leads_submitted_claims_check CHECK ((jsonb_typeof(submitted_claims) = 'object'::text))
);

--
-- Name: leads_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.leads ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.leads_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: memo_citations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memo_citations (
    memo_id bigint NOT NULL,
    fact_id bigint NOT NULL,
    source_id bigint NOT NULL,
    citation_label text NOT NULL,
    source_locator text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT memo_citations_citation_label_check CHECK ((btrim(citation_label) <> ''::text)),
    CONSTRAINT memo_citations_source_locator_check CHECK ((btrim(source_locator) <> ''::text))
);

--
-- Name: memos; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.memos (
    id bigint NOT NULL,
    lead_id bigint NOT NULL,
    workflow_run_id bigint,
    compiled_truth_id bigint NOT NULL,
    evaluation_id bigint NOT NULL,
    memo_version integer NOT NULL,
    status text DEFAULT 'draft'::text NOT NULL,
    title text NOT NULL,
    content_uri text NOT NULL,
    content_sha256 text NOT NULL,
    frozen_evidence_hash text NOT NULL,
    citation_coverage_percent numeric(5,2) NOT NULL,
    generated_by text NOT NULL,
    reviewed_by text,
    reviewed_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT memos_check CHECK (((status <> 'approved'::text) OR ((reviewed_by IS NOT NULL) AND (reviewed_at IS NOT NULL)))),
    CONSTRAINT memos_citation_coverage_percent_check CHECK (((citation_coverage_percent >= (0)::numeric) AND (citation_coverage_percent <= (100)::numeric))),
    CONSTRAINT memos_content_sha256_check CHECK ((content_sha256 ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT memos_content_uri_check CHECK ((btrim(content_uri) <> ''::text)),
    CONSTRAINT memos_frozen_evidence_hash_check CHECK ((frozen_evidence_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT memos_memo_version_check CHECK ((memo_version > 0)),
    CONSTRAINT memos_status_check CHECK ((status = ANY (ARRAY['draft'::text, 'review'::text, 'approved'::text, 'superseded'::text, 'invalid'::text]))),
    CONSTRAINT memos_title_check CHECK ((btrim(title) <> ''::text))
);

--
-- Name: memos_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.memos ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.memos_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: notification_attempts; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.notification_attempts (
    id bigint NOT NULL,
    outbox_id bigint NOT NULL,
    attempt_number integer NOT NULL,
    claim_id text NOT NULL,
    status text NOT NULL,
    provider_request_id text,
    provider_response_code text,
    provider_message_id text,
    error_class text,
    error_message text,
    started_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    finished_at timestamp with time zone,
    response_metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT notification_attempts_attempt_number_check CHECK ((attempt_number > 0)),
    CONSTRAINT notification_attempts_check CHECK (((status = 'started'::text) OR (finished_at IS NOT NULL))),
    CONSTRAINT notification_attempts_check1 CHECK (((status <> 'succeeded'::text) OR (provider_message_id IS NOT NULL))),
    CONSTRAINT notification_attempts_check2 CHECK (((status <> ALL (ARRAY['retryable_failure'::text, 'permanent_failure'::text])) OR (error_class IS NOT NULL))),
    CONSTRAINT notification_attempts_claim_id_check CHECK ((btrim(claim_id) <> ''::text)),
    CONSTRAINT notification_attempts_response_metadata_check CHECK ((jsonb_typeof(response_metadata) = 'object'::text)),
    CONSTRAINT notification_attempts_status_check CHECK ((status = ANY (ARRAY['started'::text, 'succeeded'::text, 'retryable_failure'::text, 'permanent_failure'::text, 'abandoned'::text])))
);

--
-- Name: notification_attempts_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification_attempts ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.notification_attempts_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: notification_outbox_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.notification_outbox ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.notification_outbox_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: orchestration_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.orchestration_audit (
    id bigint NOT NULL,
    lead_id bigint NOT NULL,
    workflow_run_id bigint,
    record_kind text NOT NULL,
    specialist_agent text,
    flow_id text,
    flow_revision bigint,
    task_id text,
    payload jsonb NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT orchestration_audit_check CHECK (((record_kind = 'chief_output'::text) OR (specialist_agent IS NOT NULL))),
    CONSTRAINT orchestration_audit_created_by_check CHECK ((btrim(created_by) <> ''::text)),
    CONSTRAINT orchestration_audit_flow_revision_check CHECK (((flow_revision IS NULL) OR (flow_revision >= 0))),
    CONSTRAINT orchestration_audit_payload_check CHECK ((jsonb_typeof(payload) = 'object'::text)),
    CONSTRAINT orchestration_audit_record_kind_check CHECK ((record_kind = ANY (ARRAY['delegation_eval'::text, 'return_assessment'::text, 'chief_output'::text]))),
    CONSTRAINT orchestration_audit_specialist_agent_check CHECK (((specialist_agent IS NULL) OR (btrim(specialist_agent) <> ''::text)))
);

--
-- Name: orchestration_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.orchestration_audit ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.orchestration_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: preference_forget_markers; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.preference_forget_markers (
    id bigint NOT NULL,
    principal_id bigint NOT NULL,
    preference_key text NOT NULL,
    event_id text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT preference_forget_markers_event_id_check CHECK ((btrim(event_id) <> ''::text)),
    CONSTRAINT preference_forget_markers_preference_key_check CHECK ((preference_key = ANY (ARRAY['memo_length'::text, 'communication_tone'::text, 'research_depth'::text, 'citation_density'::text, 'output_structure'::text])))
);

--
-- Name: preference_forget_markers_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.preference_forget_markers ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.preference_forget_markers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: preference_observations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.preference_observations (
    id bigint NOT NULL,
    principal_id bigint NOT NULL,
    preference_key text NOT NULL,
    preference_value text NOT NULL,
    observation_kind text NOT NULL,
    event_id text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT preference_observations_event_id_check CHECK ((btrim(event_id) <> ''::text)),
    CONSTRAINT preference_observations_observation_kind_check CHECK ((observation_kind = ANY (ARRAY['explicit'::text, 'inferred'::text]))),
    CONSTRAINT preference_observations_preference_key_check CHECK ((preference_key = ANY (ARRAY['memo_length'::text, 'communication_tone'::text, 'research_depth'::text, 'citation_density'::text, 'output_structure'::text]))),
    CONSTRAINT preference_observations_preference_value_check CHECK ((btrim(preference_value) <> ''::text))
);

--
-- Name: preference_observations_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.preference_observations ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.preference_observations_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: proposals_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.proposals ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.proposals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: schema_migrations; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.schema_migrations (
    version text NOT NULL,
    name text NOT NULL,
    checksum_sha256 text NOT NULL,
    applied_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT schema_migrations_checksum_sha256_check CHECK ((checksum_sha256 ~ '^[0-9a-f]{64}$'::text))
);

--
-- Name: signal_sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.signal_sources (
    id bigint NOT NULL,
    source_name text NOT NULL,
    canonical_uri text NOT NULL,
    source_class text NOT NULL,
    cadence text NOT NULL,
    thesis_relevance text,
    expected_signal text,
    rate_constraint text,
    owner text NOT NULL,
    confidentiality text DEFAULT 'internal'::text NOT NULL,
    enabled boolean DEFAULT true NOT NULL,
    last_scanned_at timestamp with time zone,
    last_scan_status text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    row_version bigint DEFAULT 1 NOT NULL,
    created_by text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT signal_sources_cadence_check CHECK ((cadence = ANY (ARRAY['daily'::text, 'weekly'::text, 'monthly'::text]))),
    CONSTRAINT signal_sources_canonical_uri_check CHECK (((canonical_uri = lower(btrim(canonical_uri))) AND (canonical_uri ~ '^https?://'::text))),
    CONSTRAINT signal_sources_confidentiality_check CHECK ((confidentiality = ANY (ARRAY['public'::text, 'internal'::text, 'confidential'::text, 'restricted'::text]))),
    CONSTRAINT signal_sources_created_by_check CHECK ((btrim(created_by) <> ''::text)),
    CONSTRAINT signal_sources_last_scan_status_check CHECK (((last_scan_status IS NULL) OR (last_scan_status = ANY (ARRAY['claimed'::text, 'succeeded'::text, 'no_new_signals'::text, 'failed'::text])))),
    CONSTRAINT signal_sources_metadata_check CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT signal_sources_owner_check CHECK ((btrim(owner) <> ''::text)),
    CONSTRAINT signal_sources_row_version_check CHECK ((row_version > 0)),
    CONSTRAINT signal_sources_source_class_check CHECK ((source_class = ANY (ARRAY['company_blog'::text, 'vc_portfolio'::text, 'news_rss'::text, 'press_release'::text, 'research_report'::text, 'open_source'::text, 'job_board'::text, 'other'::text]))),
    CONSTRAINT signal_sources_source_name_check CHECK ((btrim(source_name) <> ''::text))
);

--
-- Name: signal_sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.signal_sources ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.signal_sources_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: sources; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sources (
    id bigint NOT NULL,
    source_kind text NOT NULL,
    title text,
    canonical_uri text,
    provider text,
    provider_account_id text,
    stable_source_id text,
    trust_level text DEFAULT 'unknown'::text NOT NULL,
    confidentiality text DEFAULT 'internal'::text NOT NULL,
    publisher text,
    author_label text,
    published_at timestamp with time zone,
    accessed_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    content_sha256 text,
    metadata jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT sources_check CHECK (((canonical_uri IS NOT NULL) OR (stable_source_id IS NOT NULL))),
    CONSTRAINT sources_check1 CHECK (((stable_source_id IS NULL) OR (provider IS NOT NULL))),
    CONSTRAINT sources_confidentiality_check CHECK ((confidentiality = ANY (ARRAY['public'::text, 'internal'::text, 'confidential'::text, 'restricted'::text]))),
    CONSTRAINT sources_content_sha256_check CHECK (((content_sha256 IS NULL) OR (content_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT sources_metadata_check CHECK ((jsonb_typeof(metadata) = 'object'::text)),
    CONSTRAINT sources_source_kind_check CHECK ((source_kind = ANY (ARRAY['primary_document'::text, 'company_website'::text, 'regulatory_filing'::text, 'channel_message'::text, 'public_web'::text, 'paid_connector'::text, 'operator_statement'::text, 'internal_analysis'::text, 'provider_event'::text, 'other'::text]))),
    CONSTRAINT sources_trust_level_check CHECK ((trust_level = ANY (ARRAY['internal_admin'::text, 'allowlisted_operator'::text, 'remote_channel'::text, 'public_web'::text, 'paid_connector'::text, 'untrusted_upload'::text, 'generated_internal'::text, 'unknown'::text])))
);

--
-- Name: sources_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.sources ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.sources_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: trajectory_events; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trajectory_events (
    id bigint NOT NULL,
    lead_id bigint NOT NULL,
    company_id bigint NOT NULL,
    workflow_run_id bigint,
    fact_type text NOT NULL,
    definition text NOT NULL,
    direction text NOT NULL,
    status text DEFAULT 'current'::text NOT NULL,
    normalized_unit text,
    normalized_currency_code text,
    measurement_basis text,
    cohort text,
    point_count integer NOT NULL,
    calculation jsonb DEFAULT '{}'::jsonb NOT NULL,
    score_adjustment numeric(4,2) DEFAULT 0 NOT NULL,
    policy_version text NOT NULL,
    calculated_by text NOT NULL,
    calculated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT trajectory_events_calculation_check CHECK ((jsonb_typeof(calculation) = 'object'::text)),
    CONSTRAINT trajectory_events_check CHECK (((point_count >= 2) OR (direction = ANY (ARRAY['unknown_baseline'::text, 'not_comparable'::text])))),
    CONSTRAINT trajectory_events_check1 CHECK (((direction <> 'not_comparable'::text) OR (score_adjustment = (0)::numeric))),
    CONSTRAINT trajectory_events_definition_check CHECK ((btrim(definition) <> ''::text)),
    CONSTRAINT trajectory_events_direction_check CHECK ((direction = ANY (ARRAY['up'::text, 'down'::text, 'flat'::text, 'volatile'::text, 'unknown_baseline'::text, 'not_comparable'::text]))),
    CONSTRAINT trajectory_events_fact_type_check CHECK ((btrim(fact_type) <> ''::text)),
    CONSTRAINT trajectory_events_normalized_currency_code_check CHECK (((normalized_currency_code IS NULL) OR (normalized_currency_code ~ '^[A-Z]{3}$'::text))),
    CONSTRAINT trajectory_events_point_count_check CHECK ((point_count > 0)),
    CONSTRAINT trajectory_events_score_adjustment_check CHECK (((score_adjustment >= ('-5'::integer)::numeric) AND (score_adjustment <= (5)::numeric))),
    CONSTRAINT trajectory_events_status_check CHECK ((status = ANY (ARRAY['current'::text, 'superseded'::text, 'invalid'::text])))
);

--
-- Name: trajectory_events_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.trajectory_events ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.trajectory_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: trajectory_points; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trajectory_points (
    trajectory_event_id bigint NOT NULL,
    fact_id bigint NOT NULL,
    point_order integer NOT NULL,
    normalized_value numeric,
    effective_at date NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT trajectory_points_point_order_check CHECK ((point_order > 0))
);

--
-- Name: trusted_context_uses; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.trusted_context_uses (
    id bigint NOT NULL,
    principal_id bigint NOT NULL,
    nonce text NOT NULL,
    scope text NOT NULL,
    operation_key text NOT NULL,
    event_id text NOT NULL,
    run_id text NOT NULL,
    expires_at timestamp with time zone NOT NULL,
    used_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT trusted_context_uses_event_id_check CHECK ((btrim(event_id) <> ''::text)),
    CONSTRAINT trusted_context_uses_nonce_check CHECK ((nonce ~ '^[0-9a-f]{48}$'::text)),
    CONSTRAINT trusted_context_uses_operation_key_check CHECK ((btrim(operation_key) <> ''::text)),
    CONSTRAINT trusted_context_uses_run_id_check CHECK ((btrim(run_id) <> ''::text)),
    CONSTRAINT trusted_context_uses_scope_check CHECK ((btrim(scope) <> ''::text))
);

--
-- Name: trusted_context_uses_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.trusted_context_uses ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.trusted_context_uses_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: user_preference_audit; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_preference_audit (
    id bigint NOT NULL,
    principal_id bigint NOT NULL,
    preference_key text,
    action text NOT NULL,
    source_kind text,
    event_id text NOT NULL,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT user_preference_audit_action_check CHECK ((action = ANY (ARRAY['activated'::text, 'superseded'::text, 'forgotten'::text]))),
    CONSTRAINT user_preference_audit_event_id_check CHECK ((btrim(event_id) <> ''::text)),
    CONSTRAINT user_preference_audit_source_kind_check CHECK ((source_kind = ANY (ARRAY['explicit'::text, 'inferred'::text])))
);

--
-- Name: user_preference_audit_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.user_preference_audit ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.user_preference_audit_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: user_preferences; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_preferences (
    principal_id bigint NOT NULL,
    preference_key text NOT NULL,
    preference_value text,
    source_kind text,
    evidence_count integer DEFAULT 0 NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    source_event_id text,
    updated_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    CONSTRAINT user_preferences_check CHECK ((((status = 'active'::text) AND (preference_value IS NOT NULL) AND (source_kind IS NOT NULL) AND (source_event_id IS NOT NULL)) OR ((status = 'forgotten'::text) AND (preference_value IS NULL) AND (source_kind IS NULL) AND (source_event_id IS NULL)))),
    CONSTRAINT user_preferences_evidence_count_check CHECK ((evidence_count >= 0)),
    CONSTRAINT user_preferences_preference_key_check CHECK ((preference_key = ANY (ARRAY['memo_length'::text, 'communication_tone'::text, 'research_depth'::text, 'citation_density'::text, 'output_structure'::text]))),
    CONSTRAINT user_preferences_source_kind_check CHECK ((source_kind = ANY (ARRAY['explicit'::text, 'inferred'::text]))),
    CONSTRAINT user_preferences_status_check CHECK ((status = ANY (ARRAY['active'::text, 'forgotten'::text])))
);

--
-- Name: workflow_requests; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.workflow_requests (
    id bigint NOT NULL,
    workflow_id text NOT NULL,
    idempotency_key text NOT NULL,
    request_hash text NOT NULL,
    request_payload jsonb NOT NULL,
    document_sha256 text,
    created_at timestamp with time zone DEFAULT clock_timestamp() NOT NULL,
    workflow_version text DEFAULT '3.0.0'::text NOT NULL,
    policy_version text DEFAULT '3.0'::text NOT NULL,
    CONSTRAINT workflow_requests_document_sha256_check CHECK (((document_sha256 IS NULL) OR (document_sha256 ~ '^[0-9a-f]{64}$'::text))),
    CONSTRAINT workflow_requests_idempotency_key_check CHECK ((btrim(idempotency_key) <> ''::text)),
    CONSTRAINT workflow_requests_request_hash_check CHECK ((request_hash ~ '^[0-9a-f]{64}$'::text)),
    CONSTRAINT workflow_requests_request_payload_check CHECK ((jsonb_typeof(request_payload) = 'object'::text)),
    CONSTRAINT workflow_requests_version_nonempty CHECK (((btrim(workflow_version) <> ''::text) AND (btrim(policy_version) <> ''::text))),
    CONSTRAINT workflow_requests_workflow_id_check CHECK ((btrim(workflow_id) <> ''::text))
);

--
-- Name: workflow_requests_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.workflow_requests ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.workflow_requests_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: workflow_runs_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.workflow_runs ALTER COLUMN id ADD GENERATED ALWAYS AS IDENTITY (
    SEQUENCE NAME public.workflow_runs_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);

--
-- Name: approvals approvals_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_idempotency_key_key UNIQUE (idempotency_key);

--
-- Name: approvals approvals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_pkey PRIMARY KEY (id);

--
-- Name: approvals approvals_request_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_request_id_key UNIQUE (request_id);

--
-- Name: approvals approvals_token_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_token_hash_key UNIQUE (token_hash);

--
-- Name: audit_events audit_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (id);

--
-- Name: channel_principals channel_principals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_principals
    ADD CONSTRAINT channel_principals_pkey PRIMARY KEY (id);

--
-- Name: channel_principals channel_principals_provider_account_id_sender_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.channel_principals
    ADD CONSTRAINT channel_principals_provider_account_id_sender_id_key UNIQUE (provider, account_id, sender_id);

--
-- Name: companies companies_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_pkey PRIMARY KEY (id);

--
-- Name: company_aliases company_aliases_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_aliases
    ADD CONSTRAINT company_aliases_pkey PRIMARY KEY (id);

--
-- Name: company_domains company_domains_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_domains
    ADD CONSTRAINT company_domains_pkey PRIMARY KEY (id);

--
-- Name: company_external_ids company_external_ids_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_external_ids
    ADD CONSTRAINT company_external_ids_pkey PRIMARY KEY (id);

--
-- Name: compiled_truth_facts compiled_truth_facts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth_facts
    ADD CONSTRAINT compiled_truth_facts_pkey PRIMARY KEY (compiled_truth_id, fact_id, support_role);

--
-- Name: compiled_truth compiled_truth_lead_id_evidence_packet_hash_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth
    ADD CONSTRAINT compiled_truth_lead_id_evidence_packet_hash_key UNIQUE (lead_id, evidence_packet_hash);

--
-- Name: compiled_truth compiled_truth_lead_id_snapshot_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth
    ADD CONSTRAINT compiled_truth_lead_id_snapshot_version_key UNIQUE (lead_id, snapshot_version);

--
-- Name: compiled_truth compiled_truth_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth
    ADD CONSTRAINT compiled_truth_pkey PRIMARY KEY (id);

--
-- Name: contradiction_facts contradiction_facts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contradiction_facts
    ADD CONSTRAINT contradiction_facts_pkey PRIMARY KEY (contradiction_id, fact_id, assertion_role);

--
-- Name: contradictions contradictions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contradictions
    ADD CONSTRAINT contradictions_pkey PRIMARY KEY (id);

--
-- Name: document_extractions document_extractions_artifact_id_extractor_name_extractor_v_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_extractions
    ADD CONSTRAINT document_extractions_artifact_id_extractor_name_extractor_v_key UNIQUE (artifact_id, extractor_name, extractor_version, idempotency_key);

--
-- Name: document_extractions document_extractions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_extractions
    ADD CONSTRAINT document_extractions_pkey PRIMARY KEY (id);

--
-- Name: document_facts document_facts_extraction_id_fact_id_page_number_sheet_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_facts
    ADD CONSTRAINT document_facts_extraction_id_fact_id_page_number_sheet_name_key UNIQUE NULLS NOT DISTINCT (extraction_id, fact_id, page_number, sheet_name, cell_range, paragraph_number);

--
-- Name: document_facts document_facts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_facts
    ADD CONSTRAINT document_facts_pkey PRIMARY KEY (id);

--
-- Name: entity_resolution_consumptions entity_resolution_consumptions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_consumptions
    ADD CONSTRAINT entity_resolution_consumptions_pkey PRIMARY KEY (id);

--
-- Name: entity_resolution_consumptions entity_resolution_consumptions_resolution_decision_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_consumptions
    ADD CONSTRAINT entity_resolution_consumptions_resolution_decision_id_key UNIQUE (resolution_decision_id);

--
-- Name: entity_resolution_decisions entity_resolution_decisions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_decisions
    ADD CONSTRAINT entity_resolution_decisions_pkey PRIMARY KEY (id);

--
-- Name: entity_resolution_decisions entity_resolution_decisions_resolution_run_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_decisions
    ADD CONSTRAINT entity_resolution_decisions_resolution_run_id_key UNIQUE (resolution_run_id);

--
-- Name: entity_resolution_runs entity_resolution_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_runs
    ADD CONSTRAINT entity_resolution_runs_pkey PRIMARY KEY (id);

--
-- Name: evaluation_criteria evaluation_criteria_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_criteria
    ADD CONSTRAINT evaluation_criteria_pkey PRIMARY KEY (evaluation_id, criterion_key);

--
-- Name: evaluations evaluations_lead_id_evaluation_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_lead_id_evaluation_version_key UNIQUE (lead_id, evaluation_version);

--
-- Name: evaluations evaluations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_pkey PRIMARY KEY (id);

--
-- Name: evidence_artifacts evidence_artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_artifacts
    ADD CONSTRAINT evidence_artifacts_pkey PRIMARY KEY (id);

--
-- Name: evidence_artifacts evidence_artifacts_sha256_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evidence_artifacts
    ADD CONSTRAINT evidence_artifacts_sha256_key UNIQUE (sha256);

--
-- Name: fact_promotion_policy fact_promotion_policy_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_promotion_policy
    ADD CONSTRAINT fact_promotion_policy_pkey PRIMARY KEY (id);

--
-- Name: fact_sources fact_sources_fact_id_source_id_artifact_id_extraction_id_ev_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_sources
    ADD CONSTRAINT fact_sources_fact_id_source_id_artifact_id_extraction_id_ev_key UNIQUE NULLS NOT DISTINCT (fact_id, source_id, artifact_id, extraction_id, evidence_role);

--
-- Name: fact_sources fact_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_sources
    ADD CONSTRAINT fact_sources_pkey PRIMARY KEY (id);

--
-- Name: facts facts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_pkey PRIMARY KEY (id);

--
-- Name: lead_artifacts lead_artifacts_lead_id_artifact_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lead_artifacts
    ADD CONSTRAINT lead_artifacts_lead_id_artifact_id_key UNIQUE (lead_id, artifact_id);

--
-- Name: lead_artifacts lead_artifacts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lead_artifacts
    ADD CONSTRAINT lead_artifacts_pkey PRIMARY KEY (id);

--
-- Name: leads leads_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT leads_idempotency_key_key UNIQUE (idempotency_key);

--
-- Name: leads leads_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT leads_pkey PRIMARY KEY (id);

--
-- Name: memo_citations memo_citations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memo_citations
    ADD CONSTRAINT memo_citations_pkey PRIMARY KEY (memo_id, fact_id, source_id, citation_label);

--
-- Name: memos memos_lead_id_memo_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memos
    ADD CONSTRAINT memos_lead_id_memo_version_key UNIQUE (lead_id, memo_version);

--
-- Name: memos memos_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memos
    ADD CONSTRAINT memos_pkey PRIMARY KEY (id);

--
-- Name: notification_attempts notification_attempts_outbox_id_attempt_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_attempts
    ADD CONSTRAINT notification_attempts_outbox_id_attempt_number_key UNIQUE (outbox_id, attempt_number);

--
-- Name: notification_attempts notification_attempts_outbox_id_claim_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_attempts
    ADD CONSTRAINT notification_attempts_outbox_id_claim_id_key UNIQUE (outbox_id, claim_id);

--
-- Name: notification_attempts notification_attempts_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_attempts
    ADD CONSTRAINT notification_attempts_pkey PRIMARY KEY (id);

--
-- Name: notification_outbox notification_outbox_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_idempotency_key_key UNIQUE (idempotency_key);

--
-- Name: notification_outbox notification_outbox_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_pkey PRIMARY KEY (id);

--
-- Name: notification_outbox notification_outbox_provider_provider_account_id_dedupe_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_provider_provider_account_id_dedupe_key_key UNIQUE (provider, provider_account_id, dedupe_key);

--
-- Name: orchestration_audit orchestration_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestration_audit
    ADD CONSTRAINT orchestration_audit_pkey PRIMARY KEY (id);

--
-- Name: preference_forget_markers preference_forget_markers_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preference_forget_markers
    ADD CONSTRAINT preference_forget_markers_pkey PRIMARY KEY (id);

--
-- Name: preference_forget_markers preference_forget_markers_principal_id_preference_key_event_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preference_forget_markers
    ADD CONSTRAINT preference_forget_markers_principal_id_preference_key_event_key UNIQUE (principal_id, preference_key, event_id);

--
-- Name: preference_observations preference_observations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preference_observations
    ADD CONSTRAINT preference_observations_pkey PRIMARY KEY (id);

--
-- Name: preference_observations preference_observations_principal_id_preference_key_prefere_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preference_observations
    ADD CONSTRAINT preference_observations_principal_id_preference_key_prefere_key UNIQUE (principal_id, preference_key, preference_value, event_id);

--
-- Name: proposals proposals_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_pkey PRIMARY KEY (id);

--
-- Name: schema_migrations schema_migrations_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.schema_migrations
    ADD CONSTRAINT schema_migrations_pkey PRIMARY KEY (version);

--
-- Name: signal_sources signal_sources_canonical_uri_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_sources
    ADD CONSTRAINT signal_sources_canonical_uri_key UNIQUE (canonical_uri);

--
-- Name: signal_sources signal_sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.signal_sources
    ADD CONSTRAINT signal_sources_pkey PRIMARY KEY (id);

--
-- Name: sources sources_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sources
    ADD CONSTRAINT sources_pkey PRIMARY KEY (id);

--
-- Name: trajectory_events trajectory_events_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trajectory_events
    ADD CONSTRAINT trajectory_events_pkey PRIMARY KEY (id);

--
-- Name: trajectory_points trajectory_points_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trajectory_points
    ADD CONSTRAINT trajectory_points_pkey PRIMARY KEY (trajectory_event_id, point_order);

--
-- Name: trajectory_points trajectory_points_trajectory_event_id_fact_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trajectory_points
    ADD CONSTRAINT trajectory_points_trajectory_event_id_fact_id_key UNIQUE (trajectory_event_id, fact_id);

--
-- Name: trusted_context_uses trusted_context_uses_nonce_scope_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trusted_context_uses
    ADD CONSTRAINT trusted_context_uses_nonce_scope_key UNIQUE (nonce, scope);

--
-- Name: trusted_context_uses trusted_context_uses_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trusted_context_uses
    ADD CONSTRAINT trusted_context_uses_pkey PRIMARY KEY (id);

--
-- Name: user_preference_audit user_preference_audit_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preference_audit
    ADD CONSTRAINT user_preference_audit_pkey PRIMARY KEY (id);

--
-- Name: user_preference_audit user_preference_audit_principal_id_preference_key_action_ev_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preference_audit
    ADD CONSTRAINT user_preference_audit_principal_id_preference_key_action_ev_key UNIQUE (principal_id, preference_key, action, event_id);

--
-- Name: user_preferences user_preferences_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_pkey PRIMARY KEY (principal_id, preference_key);

--
-- Name: workflow_requests workflow_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_requests
    ADD CONSTRAINT workflow_requests_pkey PRIMARY KEY (id);

--
-- Name: workflow_requests workflow_requests_workflow_id_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_requests
    ADD CONSTRAINT workflow_requests_workflow_id_idempotency_key_key UNIQUE (workflow_id, idempotency_key);

--
-- Name: workflow_runs workflow_runs_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_pkey PRIMARY KEY (id);

--
-- Name: workflow_runs workflow_runs_run_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_run_id_key UNIQUE (run_id);

--
-- Name: workflow_runs workflow_runs_workflow_id_idempotency_key_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_workflow_id_idempotency_key_key UNIQUE (workflow_id, idempotency_key);

--
-- Name: approvals_pending_expiry_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX approvals_pending_expiry_idx ON public.approvals USING btree (expires_at) WHERE (status = ANY (ARRAY['pending'::text, 'approved'::text]));

--
-- Name: approvals_workflow_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX approvals_workflow_idx ON public.approvals USING btree (workflow_run_id) WHERE (workflow_run_id IS NOT NULL);

--
-- Name: audit_events_entity_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_entity_idx ON public.audit_events USING btree (entity_table, entity_id, occurred_at DESC);

--
-- Name: audit_events_transaction_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_transaction_idx ON public.audit_events USING btree (transaction_id) WHERE (transaction_id IS NOT NULL);

--
-- Name: audit_events_workflow_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX audit_events_workflow_idx ON public.audit_events USING btree (workflow_run_id, occurred_at DESC) WHERE (workflow_run_id IS NOT NULL);

--
-- Name: companies_canonical_domain_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX companies_canonical_domain_uidx ON public.companies USING btree (canonical_domain) WHERE (canonical_domain IS NOT NULL);

--
-- Name: companies_name_length_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX companies_name_length_idx ON public.companies USING btree (length(lower(name)));

--
-- Name: companies_name_lower_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX companies_name_lower_idx ON public.companies USING btree (lower(name));

--
-- Name: companies_name_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX companies_name_trgm_idx ON public.companies USING gin (lower(name) public.gin_trgm_ops);

--
-- Name: company_aliases_active_company_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX company_aliases_active_company_uidx ON public.company_aliases USING btree (company_id, normalized_alias, alias_kind) WHERE ((status = 'active'::text) AND (valid_to IS NULL));

--
-- Name: company_aliases_exact_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_aliases_exact_idx ON public.company_aliases USING btree (normalized_alias, confidentiality) WHERE ((status = 'active'::text) AND (valid_to IS NULL));

--
-- Name: company_aliases_fuzzy_bucket_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_aliases_fuzzy_bucket_idx ON public.company_aliases USING btree (lower("left"(normalized_alias, 1)), length(normalized_alias)) WHERE ((status = 'active'::text) AND (valid_to IS NULL));

--
-- Name: company_aliases_length_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_aliases_length_idx ON public.company_aliases USING btree (length(normalized_alias)) WHERE ((status = 'active'::text) AND (valid_to IS NULL));

--
-- Name: company_aliases_normalized_trgm_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_aliases_normalized_trgm_idx ON public.company_aliases USING gin (normalized_alias public.gin_trgm_ops) WHERE ((status = 'active'::text) AND (valid_to IS NULL));

--
-- Name: company_domains_active_hostname_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX company_domains_active_hostname_uidx ON public.company_domains USING btree (hostname) WHERE ((status = ANY (ARRAY['verified'::text, 'claimed'::text])) AND (valid_to IS NULL));

--
-- Name: company_domains_company_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_domains_company_idx ON public.company_domains USING btree (company_id, status, valid_to);

--
-- Name: company_external_ids_active_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX company_external_ids_active_uidx ON public.company_external_ids USING btree (provider, provider_account_id, external_id) WHERE ((status = ANY (ARRAY['verified'::text, 'claimed'::text])) AND (valid_to IS NULL));

--
-- Name: company_external_ids_company_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX company_external_ids_company_idx ON public.company_external_ids USING btree (company_id, status, valid_to);

--
-- Name: compiled_truth_company_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX compiled_truth_company_idx ON public.compiled_truth USING btree (company_id, compiled_at DESC);

--
-- Name: compiled_truth_facts_fact_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX compiled_truth_facts_fact_idx ON public.compiled_truth_facts USING btree (fact_id);

--
-- Name: compiled_truth_one_current_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX compiled_truth_one_current_uidx ON public.compiled_truth USING btree (lead_id) WHERE (status = 'current'::text);

--
-- Name: contradiction_facts_fact_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX contradiction_facts_fact_idx ON public.contradiction_facts USING btree (fact_id);

--
-- Name: contradictions_open_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX contradictions_open_idx ON public.contradictions USING btree (lead_id, severity) WHERE (status = ANY (ARRAY['open'::text, 'under_review'::text]));

--
-- Name: document_extractions_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_extractions_status_idx ON public.document_extractions USING btree (status, created_at);

--
-- Name: document_extractions_workflow_request_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX document_extractions_workflow_request_uidx ON public.document_extractions USING btree (workflow_request_id) WHERE (workflow_request_id IS NOT NULL);

--
-- Name: document_facts_fact_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX document_facts_fact_idx ON public.document_facts USING btree (fact_id);

--
-- Name: entity_resolution_consumptions_company_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX entity_resolution_consumptions_company_idx ON public.entity_resolution_consumptions USING btree (company_id, consumed_at DESC);

--
-- Name: entity_resolution_decisions_company_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX entity_resolution_decisions_company_idx ON public.entity_resolution_decisions USING btree (matched_company_id, created_at DESC) WHERE (matched_company_id IS NOT NULL);

--
-- Name: entity_resolution_decisions_outcome_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX entity_resolution_decisions_outcome_idx ON public.entity_resolution_decisions USING btree (outcome, created_at DESC);

--
-- Name: entity_resolution_runs_query_hash_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX entity_resolution_runs_query_hash_idx ON public.entity_resolution_runs USING btree (query_hash, created_at DESC);

--
-- Name: entity_resolution_runs_request_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX entity_resolution_runs_request_uidx ON public.entity_resolution_runs USING btree (requester_id, purpose, idempotency_key);

--
-- Name: entity_resolution_runs_workflow_request_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX entity_resolution_runs_workflow_request_uidx ON public.entity_resolution_runs USING btree (workflow_request_id) WHERE (workflow_request_id IS NOT NULL);

--
-- Name: evaluations_band_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX evaluations_band_idx ON public.evaluations USING btree (recommendation_band, evaluated_at DESC) WHERE (status = 'final'::text);

--
-- Name: evaluations_one_final_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX evaluations_one_final_uidx ON public.evaluations USING btree (lead_id) WHERE (status = 'final'::text);

--
-- Name: evaluations_request_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX evaluations_request_uidx ON public.evaluations USING btree (lead_id, request_hash) WHERE (request_hash IS NOT NULL);

--
-- Name: evidence_artifacts_retention_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX evidence_artifacts_retention_idx ON public.evidence_artifacts USING btree (retention_class, created_at);

--
-- Name: evidence_artifacts_type_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX evidence_artifacts_type_idx ON public.evidence_artifacts USING btree (artifact_type, collected_at DESC);

--
-- Name: fact_sources_artifact_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fact_sources_artifact_idx ON public.fact_sources USING btree (artifact_id) WHERE (artifact_id IS NOT NULL);

--
-- Name: fact_sources_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX fact_sources_source_idx ON public.fact_sources USING btree (source_id, fact_id);

--
-- Name: facts_claim_hash_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX facts_claim_hash_idx ON public.facts USING btree (company_id, claim_hash) WHERE (claim_hash IS NOT NULL);

--
-- Name: facts_definition_time_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX facts_definition_time_idx ON public.facts USING btree (company_id, fact_type, definition, period_start, period_end, observed_at DESC);

--
-- Name: facts_lead_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX facts_lead_status_idx ON public.facts USING btree (lead_id, fact_status);

--
-- Name: facts_supersedes_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX facts_supersedes_idx ON public.facts USING btree (supersedes_fact_id) WHERE (supersedes_fact_id IS NOT NULL);

--
-- Name: lead_artifacts_artifact_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX lead_artifacts_artifact_idx ON public.lead_artifacts USING btree (artifact_id, lead_id);

--
-- Name: lead_artifacts_source_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX lead_artifacts_source_idx ON public.lead_artifacts USING btree (source_id) WHERE (source_id IS NOT NULL);

--
-- Name: leads_company_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX leads_company_status_idx ON public.leads USING btree (company_id, status);

--
-- Name: leads_created_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX leads_created_at_idx ON public.leads USING btree (created_at DESC);

--
-- Name: leads_provider_event_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX leads_provider_event_uidx ON public.leads USING btree (channel_provider, channel_account_id, channel_event_id) WHERE ((channel_provider IS NOT NULL) AND (channel_account_id IS NOT NULL) AND (channel_event_id IS NOT NULL));

--
-- Name: memo_citations_fact_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX memo_citations_fact_idx ON public.memo_citations USING btree (fact_id, source_id);

--
-- Name: memos_content_lineage_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX memos_content_lineage_uidx ON public.memos USING btree (lead_id, compiled_truth_id, evaluation_id, content_sha256);

--
-- Name: memos_one_approved_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX memos_one_approved_uidx ON public.memos USING btree (lead_id) WHERE (status = 'approved'::text);

--
-- Name: notification_attempt_provider_request_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_attempt_provider_request_idx ON public.notification_attempts USING btree (provider_request_id) WHERE (provider_request_id IS NOT NULL);

--
-- Name: notification_outbox_dispatch_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbox_dispatch_idx ON public.notification_outbox USING btree (COALESCE(next_attempt_at, deliver_after), id) WHERE (status = ANY (ARRAY['queued'::text, 'retry'::text]));

--
-- Name: notification_outbox_held_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX notification_outbox_held_idx ON public.notification_outbox USING btree (deliver_after, id) WHERE (status = 'held'::text);

--
-- Name: notification_provider_message_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX notification_provider_message_uidx ON public.notification_outbox USING btree (provider, provider_account_id, provider_message_id) WHERE (provider_message_id IS NOT NULL);

--
-- Name: orchestration_audit_lead_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX orchestration_audit_lead_idx ON public.orchestration_audit USING btree (lead_id, created_at DESC);

--
-- Name: orchestration_audit_run_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX orchestration_audit_run_idx ON public.orchestration_audit USING btree (workflow_run_id) WHERE (workflow_run_id IS NOT NULL);

--
-- Name: preference_forget_markers_cutoff_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX preference_forget_markers_cutoff_idx ON public.preference_forget_markers USING btree (principal_id, preference_key, created_at DESC);

--
-- Name: preference_observations_activation_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX preference_observations_activation_idx ON public.preference_observations USING btree (principal_id, preference_key, preference_value, observation_kind);

--
-- Name: proposals_kind_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX proposals_kind_idx ON public.proposals USING btree (proposal_kind, created_at DESC);

--
-- Name: proposals_status_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX proposals_status_idx ON public.proposals USING btree (status, created_at DESC);

--
-- Name: signal_sources_due_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX signal_sources_due_idx ON public.signal_sources USING btree (cadence, last_scanned_at) WHERE enabled;

--
-- Name: sources_canonical_uri_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sources_canonical_uri_idx ON public.sources USING btree (canonical_uri) WHERE (canonical_uri IS NOT NULL);

--
-- Name: sources_provider_stable_uidx; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX sources_provider_stable_uidx ON public.sources USING btree (provider, provider_account_id, stable_source_id) NULLS NOT DISTINCT WHERE (stable_source_id IS NOT NULL);

--
-- Name: sources_published_at_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX sources_published_at_idx ON public.sources USING btree (published_at DESC);

--
-- Name: trajectory_events_lead_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trajectory_events_lead_idx ON public.trajectory_events USING btree (lead_id, fact_type, calculated_at DESC);

--
-- Name: trajectory_points_fact_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trajectory_points_fact_idx ON public.trajectory_points USING btree (fact_id);

--
-- Name: trusted_context_uses_principal_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX trusted_context_uses_principal_idx ON public.trusted_context_uses USING btree (principal_id, used_at DESC);

--
-- Name: workflow_runs_active_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX workflow_runs_active_idx ON public.workflow_runs USING btree (status, heartbeat_at) WHERE (status = ANY (ARRAY['queued'::text, 'started'::text, 'running'::text, 'waiting'::text, 'blocked'::text]));

--
-- Name: workflow_runs_external_flow_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX workflow_runs_external_flow_idx ON public.workflow_runs USING btree (external_flow_id) WHERE (external_flow_id IS NOT NULL);

--
-- Name: workflow_runs_lead_idx; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX workflow_runs_lead_idx ON public.workflow_runs USING btree (lead_id, created_at DESC);

--
-- Name: approvals approvals_guard_transition; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER approvals_guard_transition BEFORE INSERT OR UPDATE ON public.approvals FOR EACH ROW EXECUTE FUNCTION public.guard_approval_transition();

--
-- Name: approvals approvals_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER approvals_set_updated_at BEFORE UPDATE ON public.approvals FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

--
-- Name: audit_events audit_events_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER audit_events_append_only BEFORE DELETE OR UPDATE OR TRUNCATE ON public.audit_events FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_audit_mutation();

--
-- Name: companies companies_touch_version; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER companies_touch_version BEFORE UPDATE ON public.companies FOR EACH ROW EXECUTE FUNCTION public.touch_versioned_row();

--
-- Name: compiled_truth_facts compiled_truth_facts_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER compiled_truth_facts_append_only BEFORE DELETE OR UPDATE ON public.compiled_truth_facts FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: compiled_truth_facts compiled_truth_facts_guard; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER compiled_truth_facts_guard BEFORE INSERT OR UPDATE ON public.compiled_truth_facts FOR EACH ROW EXECUTE FUNCTION public.guard_compiled_truth_fact();

--
-- Name: compiled_truth compiled_truth_lineage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER compiled_truth_lineage BEFORE INSERT OR UPDATE OF lead_id, company_id, workflow_run_id ON public.compiled_truth FOR EACH ROW EXECUTE FUNCTION public.guard_compiled_truth_lineage();

--
-- Name: contradiction_facts contradiction_facts_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER contradiction_facts_append_only BEFORE DELETE OR UPDATE ON public.contradiction_facts FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: contradictions contradictions_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER contradictions_set_updated_at BEFORE UPDATE ON public.contradictions FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

--
-- Name: document_extractions document_extractions_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER document_extractions_set_updated_at BEFORE UPDATE ON public.document_extractions FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

--
-- Name: document_extractions document_extractions_workflow_request_lineage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER document_extractions_workflow_request_lineage BEFORE INSERT OR UPDATE OF artifact_id, workflow_run_id, idempotency_key, workflow_request_id ON public.document_extractions FOR EACH ROW EXECUTE FUNCTION public.guard_document_workflow_request();

--
-- Name: document_extractions document_extractions_workflow_versions; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER document_extractions_workflow_versions BEFORE INSERT OR UPDATE OF workflow_request_id, workflow_run_id ON public.document_extractions FOR EACH ROW EXECUTE FUNCTION public.guard_document_workflow_versions();

--
-- Name: document_facts document_facts_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER document_facts_append_only BEFORE DELETE OR UPDATE ON public.document_facts FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: entity_resolution_consumptions entity_resolution_consumptions_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER entity_resolution_consumptions_append_only BEFORE DELETE OR UPDATE ON public.entity_resolution_consumptions FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: entity_resolution_decisions entity_resolution_decisions_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER entity_resolution_decisions_append_only BEFORE DELETE OR UPDATE ON public.entity_resolution_decisions FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: entity_resolution_runs entity_resolution_runs_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER entity_resolution_runs_append_only BEFORE DELETE OR UPDATE ON public.entity_resolution_runs FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: evaluation_criteria evaluation_criteria_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER evaluation_criteria_append_only BEFORE DELETE OR UPDATE ON public.evaluation_criteria FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: evaluations evaluations_lineage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER evaluations_lineage BEFORE INSERT OR UPDATE OF lead_id, workflow_run_id, compiled_truth_id, status, evidence_packet_hash ON public.evaluations FOR EACH ROW EXECUTE FUNCTION public.guard_evaluation_lineage();

--
-- Name: evidence_artifacts evidence_artifacts_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER evidence_artifacts_set_updated_at BEFORE UPDATE ON public.evidence_artifacts FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

--
-- Name: fact_sources fact_sources_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER fact_sources_append_only BEFORE DELETE OR UPDATE ON public.fact_sources FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: facts facts_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER facts_append_only BEFORE DELETE OR UPDATE ON public.facts FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: facts facts_lineage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER facts_lineage BEFORE INSERT ON public.facts FOR EACH ROW EXECUTE FUNCTION public.guard_fact_lineage();

--
-- Name: leads leads_touch_version; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER leads_touch_version BEFORE UPDATE ON public.leads FOR EACH ROW EXECUTE FUNCTION public.touch_versioned_row();

--
-- Name: memo_citations memo_citations_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER memo_citations_append_only BEFORE DELETE OR UPDATE ON public.memo_citations FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: memo_citations memo_citations_lineage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER memo_citations_lineage BEFORE INSERT ON public.memo_citations FOR EACH ROW EXECUTE FUNCTION public.guard_memo_citation_lineage();

--
-- Name: memos memos_lineage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER memos_lineage BEFORE INSERT OR UPDATE OF lead_id, workflow_run_id, compiled_truth_id, evaluation_id, frozen_evidence_hash ON public.memos FOR EACH ROW EXECUTE FUNCTION public.guard_memo_lineage();

--
-- Name: memos memos_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER memos_set_updated_at BEFORE UPDATE ON public.memos FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

--
-- Name: notification_outbox notification_outbox_guard_initial; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER notification_outbox_guard_initial BEFORE INSERT ON public.notification_outbox FOR EACH ROW EXECUTE FUNCTION public.guard_initial_notification();

--
-- Name: notification_outbox notification_outbox_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER notification_outbox_set_updated_at BEFORE UPDATE ON public.notification_outbox FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

--
-- Name: orchestration_audit orchestration_audit_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER orchestration_audit_append_only BEFORE DELETE OR UPDATE ON public.orchestration_audit FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: orchestration_audit orchestration_audit_lineage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER orchestration_audit_lineage BEFORE INSERT ON public.orchestration_audit FOR EACH ROW EXECUTE FUNCTION public.guard_orchestration_audit_lineage();

--
-- Name: preference_forget_markers preference_forget_markers_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER preference_forget_markers_append_only BEFORE DELETE OR UPDATE ON public.preference_forget_markers FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: preference_observations preference_observations_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER preference_observations_append_only BEFORE DELETE OR UPDATE ON public.preference_observations FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: proposals proposals_guard_decision; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER proposals_guard_decision BEFORE INSERT OR UPDATE ON public.proposals FOR EACH ROW EXECUTE FUNCTION public.guard_proposal_decision();

--
-- Name: proposals proposals_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER proposals_set_updated_at BEFORE UPDATE ON public.proposals FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

--
-- Name: schema_migrations schema_migrations_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER schema_migrations_append_only BEFORE DELETE OR UPDATE OR TRUNCATE ON public.schema_migrations FOR EACH STATEMENT EXECUTE FUNCTION public.prevent_migration_record_mutation();

--
-- Name: signal_sources signal_sources_touch_version; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER signal_sources_touch_version BEFORE UPDATE ON public.signal_sources FOR EACH ROW EXECUTE FUNCTION public.touch_versioned_row();

--
-- Name: sources sources_set_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER sources_set_updated_at BEFORE UPDATE ON public.sources FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

--
-- Name: trajectory_points trajectory_points_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trajectory_points_append_only BEFORE DELETE OR UPDATE ON public.trajectory_points FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: trusted_context_uses trusted_context_uses_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trusted_context_uses_append_only BEFORE DELETE OR UPDATE ON public.trusted_context_uses FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: user_preference_audit user_preference_audit_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER user_preference_audit_append_only BEFORE DELETE OR UPDATE ON public.user_preference_audit FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: workflow_requests workflow_requests_append_only; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER workflow_requests_append_only BEFORE DELETE OR UPDATE ON public.workflow_requests FOR EACH ROW EXECUTE FUNCTION public.prevent_domain_history_mutation();

--
-- Name: workflow_runs workflow_runs_guard_initial; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER workflow_runs_guard_initial BEFORE INSERT ON public.workflow_runs FOR EACH ROW EXECUTE FUNCTION public.guard_initial_workflow_run();

--
-- Name: workflow_runs workflow_runs_guard_transition; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER workflow_runs_guard_transition BEFORE UPDATE ON public.workflow_runs FOR EACH ROW EXECUTE FUNCTION public.guard_workflow_run_transition();

--
-- Name: workflow_runs workflow_runs_identity_immutable; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER workflow_runs_identity_immutable BEFORE UPDATE OF workflow_id, workflow_version, policy_version, idempotency_key, input_hash ON public.workflow_runs FOR EACH ROW EXECUTE FUNCTION public.guard_workflow_run_identity();

--
-- Name: workflow_runs workflow_runs_lineage; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER workflow_runs_lineage BEFORE INSERT OR UPDATE OF lead_id, company_id ON public.workflow_runs FOR EACH ROW EXECUTE FUNCTION public.guard_workflow_lineage();

--
-- Name: approvals approvals_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: approvals approvals_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: approvals approvals_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.approvals
    ADD CONSTRAINT approvals_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: audit_events audit_events_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: company_aliases company_aliases_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_aliases
    ADD CONSTRAINT company_aliases_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: company_aliases company_aliases_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_aliases
    ADD CONSTRAINT company_aliases_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id) ON DELETE RESTRICT;

--
-- Name: company_domains company_domains_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_domains
    ADD CONSTRAINT company_domains_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: company_domains company_domains_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_domains
    ADD CONSTRAINT company_domains_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id) ON DELETE RESTRICT;

--
-- Name: company_external_ids company_external_ids_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_external_ids
    ADD CONSTRAINT company_external_ids_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: company_external_ids company_external_ids_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.company_external_ids
    ADD CONSTRAINT company_external_ids_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id) ON DELETE RESTRICT;

--
-- Name: compiled_truth compiled_truth_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth
    ADD CONSTRAINT compiled_truth_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: compiled_truth_facts compiled_truth_facts_compiled_truth_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth_facts
    ADD CONSTRAINT compiled_truth_facts_compiled_truth_id_fkey FOREIGN KEY (compiled_truth_id) REFERENCES public.compiled_truth(id) ON DELETE RESTRICT;

--
-- Name: compiled_truth_facts compiled_truth_facts_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth_facts
    ADD CONSTRAINT compiled_truth_facts_fact_id_fkey FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE RESTRICT;

--
-- Name: compiled_truth compiled_truth_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth
    ADD CONSTRAINT compiled_truth_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: compiled_truth compiled_truth_prior_snapshot_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth
    ADD CONSTRAINT compiled_truth_prior_snapshot_id_fkey FOREIGN KEY (prior_snapshot_id) REFERENCES public.compiled_truth(id) ON DELETE RESTRICT;

--
-- Name: compiled_truth compiled_truth_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.compiled_truth
    ADD CONSTRAINT compiled_truth_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: contradiction_facts contradiction_facts_contradiction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contradiction_facts
    ADD CONSTRAINT contradiction_facts_contradiction_id_fkey FOREIGN KEY (contradiction_id) REFERENCES public.contradictions(id) ON DELETE RESTRICT;

--
-- Name: contradiction_facts contradiction_facts_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contradiction_facts
    ADD CONSTRAINT contradiction_facts_fact_id_fkey FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE RESTRICT;

--
-- Name: contradictions contradictions_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contradictions
    ADD CONSTRAINT contradictions_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: contradictions contradictions_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contradictions
    ADD CONSTRAINT contradictions_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: contradictions contradictions_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.contradictions
    ADD CONSTRAINT contradictions_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: document_extractions document_extractions_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_extractions
    ADD CONSTRAINT document_extractions_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.evidence_artifacts(id) ON DELETE RESTRICT;

--
-- Name: document_extractions document_extractions_workflow_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_extractions
    ADD CONSTRAINT document_extractions_workflow_request_id_fkey FOREIGN KEY (workflow_request_id) REFERENCES public.workflow_requests(id) ON DELETE RESTRICT;

--
-- Name: document_extractions document_extractions_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_extractions
    ADD CONSTRAINT document_extractions_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: document_facts document_facts_extraction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_facts
    ADD CONSTRAINT document_facts_extraction_id_fkey FOREIGN KEY (extraction_id) REFERENCES public.document_extractions(id) ON DELETE RESTRICT;

--
-- Name: document_facts document_facts_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_facts
    ADD CONSTRAINT document_facts_fact_id_fkey FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE RESTRICT;

--
-- Name: entity_resolution_consumptions entity_resolution_consumptions_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_consumptions
    ADD CONSTRAINT entity_resolution_consumptions_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: entity_resolution_consumptions entity_resolution_consumptions_resolution_decision_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_consumptions
    ADD CONSTRAINT entity_resolution_consumptions_resolution_decision_id_fkey FOREIGN KEY (resolution_decision_id) REFERENCES public.entity_resolution_decisions(id) ON DELETE RESTRICT;

--
-- Name: entity_resolution_decisions entity_resolution_decisions_matched_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_decisions
    ADD CONSTRAINT entity_resolution_decisions_matched_company_id_fkey FOREIGN KEY (matched_company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: entity_resolution_decisions entity_resolution_decisions_resolution_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_decisions
    ADD CONSTRAINT entity_resolution_decisions_resolution_run_id_fkey FOREIGN KEY (resolution_run_id) REFERENCES public.entity_resolution_runs(id) ON DELETE RESTRICT;

--
-- Name: entity_resolution_runs entity_resolution_runs_workflow_request_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.entity_resolution_runs
    ADD CONSTRAINT entity_resolution_runs_workflow_request_id_fkey FOREIGN KEY (workflow_request_id) REFERENCES public.workflow_requests(id) ON DELETE RESTRICT;

--
-- Name: evaluation_criteria evaluation_criteria_evaluation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluation_criteria
    ADD CONSTRAINT evaluation_criteria_evaluation_id_fkey FOREIGN KEY (evaluation_id) REFERENCES public.evaluations(id) ON DELETE RESTRICT;

--
-- Name: evaluations evaluations_compiled_truth_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_compiled_truth_id_fkey FOREIGN KEY (compiled_truth_id) REFERENCES public.compiled_truth(id) ON DELETE RESTRICT;

--
-- Name: evaluations evaluations_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: evaluations evaluations_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.evaluations
    ADD CONSTRAINT evaluations_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: fact_sources fact_sources_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_sources
    ADD CONSTRAINT fact_sources_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.evidence_artifacts(id) ON DELETE RESTRICT;

--
-- Name: fact_sources fact_sources_extraction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_sources
    ADD CONSTRAINT fact_sources_extraction_id_fkey FOREIGN KEY (extraction_id) REFERENCES public.document_extractions(id) ON DELETE RESTRICT;

--
-- Name: fact_sources fact_sources_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_sources
    ADD CONSTRAINT fact_sources_fact_id_fkey FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE RESTRICT;

--
-- Name: fact_sources fact_sources_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.fact_sources
    ADD CONSTRAINT fact_sources_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id) ON DELETE RESTRICT;

--
-- Name: facts facts_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: facts facts_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: facts facts_supersedes_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_supersedes_fact_id_fkey FOREIGN KEY (supersedes_fact_id) REFERENCES public.facts(id) ON DELETE RESTRICT;

--
-- Name: facts facts_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.facts
    ADD CONSTRAINT facts_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: lead_artifacts lead_artifacts_artifact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lead_artifacts
    ADD CONSTRAINT lead_artifacts_artifact_id_fkey FOREIGN KEY (artifact_id) REFERENCES public.evidence_artifacts(id) ON DELETE RESTRICT;

--
-- Name: lead_artifacts lead_artifacts_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lead_artifacts
    ADD CONSTRAINT lead_artifacts_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: lead_artifacts lead_artifacts_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.lead_artifacts
    ADD CONSTRAINT lead_artifacts_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id) ON DELETE RESTRICT;

--
-- Name: leads leads_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leads
    ADD CONSTRAINT leads_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: memo_citations memo_citations_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memo_citations
    ADD CONSTRAINT memo_citations_fact_id_fkey FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE RESTRICT;

--
-- Name: memo_citations memo_citations_memo_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memo_citations
    ADD CONSTRAINT memo_citations_memo_id_fkey FOREIGN KEY (memo_id) REFERENCES public.memos(id) ON DELETE RESTRICT;

--
-- Name: memo_citations memo_citations_source_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memo_citations
    ADD CONSTRAINT memo_citations_source_id_fkey FOREIGN KEY (source_id) REFERENCES public.sources(id) ON DELETE RESTRICT;

--
-- Name: memos memos_compiled_truth_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memos
    ADD CONSTRAINT memos_compiled_truth_id_fkey FOREIGN KEY (compiled_truth_id) REFERENCES public.compiled_truth(id) ON DELETE RESTRICT;

--
-- Name: memos memos_evaluation_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memos
    ADD CONSTRAINT memos_evaluation_id_fkey FOREIGN KEY (evaluation_id) REFERENCES public.evaluations(id) ON DELETE RESTRICT;

--
-- Name: memos memos_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memos
    ADD CONSTRAINT memos_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: memos memos_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.memos
    ADD CONSTRAINT memos_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: notification_attempts notification_attempts_outbox_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_attempts
    ADD CONSTRAINT notification_attempts_outbox_id_fkey FOREIGN KEY (outbox_id) REFERENCES public.notification_outbox(id) ON DELETE RESTRICT;

--
-- Name: notification_outbox notification_outbox_approval_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_approval_id_fkey FOREIGN KEY (approval_id) REFERENCES public.approvals(id) ON DELETE RESTRICT;

--
-- Name: notification_outbox notification_outbox_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: notification_outbox notification_outbox_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: notification_outbox notification_outbox_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.notification_outbox
    ADD CONSTRAINT notification_outbox_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: orchestration_audit orchestration_audit_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestration_audit
    ADD CONSTRAINT orchestration_audit_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: orchestration_audit orchestration_audit_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.orchestration_audit
    ADD CONSTRAINT orchestration_audit_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: preference_forget_markers preference_forget_markers_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preference_forget_markers
    ADD CONSTRAINT preference_forget_markers_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.channel_principals(id) ON DELETE RESTRICT;

--
-- Name: preference_observations preference_observations_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.preference_observations
    ADD CONSTRAINT preference_observations_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.channel_principals(id) ON DELETE RESTRICT;

--
-- Name: proposals proposals_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: proposals proposals_supersedes_proposal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.proposals
    ADD CONSTRAINT proposals_supersedes_proposal_id_fkey FOREIGN KEY (supersedes_proposal_id) REFERENCES public.proposals(id) ON DELETE RESTRICT;

--
-- Name: trajectory_events trajectory_events_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trajectory_events
    ADD CONSTRAINT trajectory_events_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: trajectory_events trajectory_events_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trajectory_events
    ADD CONSTRAINT trajectory_events_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: trajectory_events trajectory_events_workflow_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trajectory_events
    ADD CONSTRAINT trajectory_events_workflow_run_id_fkey FOREIGN KEY (workflow_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: trajectory_points trajectory_points_fact_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trajectory_points
    ADD CONSTRAINT trajectory_points_fact_id_fkey FOREIGN KEY (fact_id) REFERENCES public.facts(id) ON DELETE RESTRICT;

--
-- Name: trajectory_points trajectory_points_trajectory_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trajectory_points
    ADD CONSTRAINT trajectory_points_trajectory_event_id_fkey FOREIGN KEY (trajectory_event_id) REFERENCES public.trajectory_events(id) ON DELETE RESTRICT;

--
-- Name: trusted_context_uses trusted_context_uses_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.trusted_context_uses
    ADD CONSTRAINT trusted_context_uses_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.channel_principals(id) ON DELETE RESTRICT;

--
-- Name: user_preference_audit user_preference_audit_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preference_audit
    ADD CONSTRAINT user_preference_audit_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.channel_principals(id) ON DELETE RESTRICT;

--
-- Name: user_preferences user_preferences_principal_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_preferences
    ADD CONSTRAINT user_preferences_principal_id_fkey FOREIGN KEY (principal_id) REFERENCES public.channel_principals(id) ON DELETE RESTRICT;

--
-- Name: workflow_runs workflow_runs_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE RESTRICT;

--
-- Name: workflow_runs workflow_runs_lead_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_lead_id_fkey FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE RESTRICT;

--
-- Name: workflow_runs workflow_runs_parent_run_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.workflow_runs
    ADD CONSTRAINT workflow_runs_parent_run_id_fkey FOREIGN KEY (parent_run_id) REFERENCES public.workflow_runs(id) ON DELETE RESTRICT;

--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA public TO openclaw_runtime;

--
-- Name: FUNCTION gtrgm_in(cstring); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_in(cstring) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_out(public.gtrgm); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_out(public.gtrgm) FROM PUBLIC;

--
-- Name: TABLE notification_outbox; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.notification_outbox TO openclaw_runtime;

--
-- Name: FUNCTION cancel_notification(p_outbox_id bigint, p_actor_id text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.cancel_notification(p_outbox_id bigint, p_actor_id text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.cancel_notification(p_outbox_id bigint, p_actor_id text) TO openclaw_runtime;

--
-- Name: FUNCTION claim_notification(p_worker_id text, p_lease_seconds integer); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.claim_notification(p_worker_id text, p_lease_seconds integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.claim_notification(p_worker_id text, p_lease_seconds integer) TO openclaw_runtime;

--
-- Name: TABLE approvals; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.approvals TO openclaw_runtime;

--
-- Name: FUNCTION consume_approval(p_token_hash text, p_scope_hash text, p_action_type text, p_target_system text, p_payload_hash text, p_governed_transaction_id text, p_actor_id text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.consume_approval(p_token_hash text, p_scope_hash text, p_action_type text, p_target_system text, p_payload_hash text, p_governed_transaction_id text, p_actor_id text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.consume_approval(p_token_hash text, p_scope_hash text, p_action_type text, p_target_system text, p_payload_hash text, p_governed_transaction_id text, p_actor_id text) TO openclaw_runtime;

--
-- Name: FUNCTION consume_approval_and_erase_lead(p_lead_id bigint, p_token_hash text, p_scope_hash text, p_action_type text, p_target_system text, p_payload_hash text, p_governed_transaction_id text, p_actor_id text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.consume_approval_and_erase_lead(p_lead_id bigint, p_token_hash text, p_scope_hash text, p_action_type text, p_target_system text, p_payload_hash text, p_governed_transaction_id text, p_actor_id text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.consume_approval_and_erase_lead(p_lead_id bigint, p_token_hash text, p_scope_hash text, p_action_type text, p_target_system text, p_payload_hash text, p_governed_transaction_id text, p_actor_id text) TO openclaw_runtime;

--
-- Name: FUNCTION decide_approval(p_request_id text, p_decision text, p_approver_id text, p_approval_channel_id text, p_note text, p_actor_id text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.decide_approval(p_request_id text, p_decision text, p_approver_id text, p_approval_channel_id text, p_note text, p_actor_id text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.decide_approval(p_request_id text, p_decision text, p_approver_id text, p_approval_channel_id text, p_note text, p_actor_id text) TO openclaw_runtime;

--
-- Name: TABLE proposals; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.proposals TO openclaw_runtime;

--
-- Name: FUNCTION decide_proposal(p_proposal_id bigint, p_decision text, p_reviewed_by text, p_review_note text, p_actor_id text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.decide_proposal(p_proposal_id bigint, p_decision text, p_reviewed_by text, p_review_note text, p_actor_id text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.decide_proposal(p_proposal_id bigint, p_decision text, p_reviewed_by text, p_review_note text, p_actor_id text) TO openclaw_runtime;

--
-- Name: FUNCTION finish_notification_attempt(p_outbox_id bigint, p_claim_id text, p_outcome text, p_provider_request_id text, p_provider_response_code text, p_provider_message_id text, p_error_class text, p_error_message text, p_retry_after_seconds integer); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.finish_notification_attempt(p_outbox_id bigint, p_claim_id text, p_outcome text, p_provider_request_id text, p_provider_response_code text, p_provider_message_id text, p_error_class text, p_error_message text, p_retry_after_seconds integer) FROM PUBLIC;
GRANT ALL ON FUNCTION public.finish_notification_attempt(p_outbox_id bigint, p_claim_id text, p_outcome text, p_provider_request_id text, p_provider_response_code text, p_provider_message_id text, p_error_class text, p_error_message text, p_retry_after_seconds integer) TO openclaw_runtime;

--
-- Name: FUNCTION gin_extract_query_trgm(text, internal, smallint, internal, internal, internal, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gin_extract_query_trgm(text, internal, smallint, internal, internal, internal, internal) FROM PUBLIC;

--
-- Name: FUNCTION gin_extract_value_trgm(text, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gin_extract_value_trgm(text, internal) FROM PUBLIC;

--
-- Name: FUNCTION gin_trgm_consistent(internal, smallint, text, integer, internal, internal, internal, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gin_trgm_consistent(internal, smallint, text, integer, internal, internal, internal, internal) FROM PUBLIC;

--
-- Name: FUNCTION gin_trgm_triconsistent(internal, smallint, text, integer, internal, internal, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gin_trgm_triconsistent(internal, smallint, text, integer, internal, internal, internal) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_compress(internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_compress(internal) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_consistent(internal, text, smallint, oid, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_consistent(internal, text, smallint, oid, internal) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_decompress(internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_decompress(internal) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_distance(internal, text, smallint, oid, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_distance(internal, text, smallint, oid, internal) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_options(internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_options(internal) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_penalty(internal, internal, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_penalty(internal, internal, internal) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_picksplit(internal, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_picksplit(internal, internal) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_same(public.gtrgm, public.gtrgm, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_same(public.gtrgm, public.gtrgm, internal) FROM PUBLIC;

--
-- Name: FUNCTION gtrgm_union(internal, internal); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.gtrgm_union(internal, internal) FROM PUBLIC;

--
-- Name: FUNCTION guard_approval_transition(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_approval_transition() FROM PUBLIC;

--
-- Name: FUNCTION guard_compiled_truth_fact(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_compiled_truth_fact() FROM PUBLIC;

--
-- Name: FUNCTION guard_compiled_truth_lineage(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_compiled_truth_lineage() FROM PUBLIC;

--
-- Name: FUNCTION guard_document_workflow_request(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_document_workflow_request() FROM PUBLIC;

--
-- Name: FUNCTION guard_document_workflow_versions(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_document_workflow_versions() FROM PUBLIC;

--
-- Name: FUNCTION guard_evaluation_lineage(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_evaluation_lineage() FROM PUBLIC;

--
-- Name: FUNCTION guard_fact_lineage(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_fact_lineage() FROM PUBLIC;

--
-- Name: FUNCTION guard_initial_notification(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_initial_notification() FROM PUBLIC;

--
-- Name: FUNCTION guard_initial_workflow_run(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_initial_workflow_run() FROM PUBLIC;

--
-- Name: FUNCTION guard_memo_citation_lineage(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_memo_citation_lineage() FROM PUBLIC;

--
-- Name: FUNCTION guard_memo_lineage(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_memo_lineage() FROM PUBLIC;

--
-- Name: FUNCTION guard_orchestration_audit_lineage(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_orchestration_audit_lineage() FROM PUBLIC;

--
-- Name: FUNCTION guard_proposal_decision(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_proposal_decision() FROM PUBLIC;

--
-- Name: FUNCTION guard_workflow_lineage(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_workflow_lineage() FROM PUBLIC;

--
-- Name: FUNCTION guard_workflow_run_identity(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_workflow_run_identity() FROM PUBLIC;

--
-- Name: FUNCTION guard_workflow_run_transition(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.guard_workflow_run_transition() FROM PUBLIC;

--
-- Name: FUNCTION prevent_audit_mutation(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.prevent_audit_mutation() FROM PUBLIC;

--
-- Name: FUNCTION prevent_domain_history_mutation(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.prevent_domain_history_mutation() FROM PUBLIC;

--
-- Name: FUNCTION prevent_migration_record_mutation(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.prevent_migration_record_mutation() FROM PUBLIC;

--
-- Name: TABLE facts; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.facts TO openclaw_runtime;

--
-- Name: FUNCTION promote_submitted_claim(p_fact_id bigint, p_actor text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.promote_submitted_claim(p_fact_id bigint, p_actor text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.promote_submitted_claim(p_fact_id bigint, p_actor text) TO openclaw_runtime;

--
-- Name: FUNCTION register_schema_migration(p_version text, p_name text, p_checksum_sha256 text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.register_schema_migration(p_version text, p_name text, p_checksum_sha256 text) FROM PUBLIC;

--
-- Name: FUNCTION registrable_host(p_host text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.registrable_host(p_host text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.registrable_host(p_host text) TO openclaw_runtime;

--
-- Name: FUNCTION release_held_notification(p_outbox_id bigint, p_actor_id text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.release_held_notification(p_outbox_id bigint, p_actor_id text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.release_held_notification(p_outbox_id bigint, p_actor_id text) TO openclaw_runtime;

--
-- Name: TABLE workflow_runs; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.workflow_runs TO openclaw_runtime;

--
-- Name: FUNCTION request_workflow_cancel(p_run_id text, p_expected_record_version bigint, p_actor_id text, p_reason text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.request_workflow_cancel(p_run_id text, p_expected_record_version bigint, p_actor_id text, p_reason text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.request_workflow_cancel(p_run_id text, p_expected_record_version bigint, p_actor_id text, p_reason text) TO openclaw_runtime;

--
-- Name: FUNCTION set_limit(real); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.set_limit(real) FROM PUBLIC;

--
-- Name: FUNCTION set_updated_at(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.set_updated_at() FROM PUBLIC;

--
-- Name: FUNCTION show_limit(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.show_limit() FROM PUBLIC;

--
-- Name: FUNCTION show_trgm(text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.show_trgm(text) FROM PUBLIC;

--
-- Name: FUNCTION signal_source_is_due(p_cadence text, p_last_scanned_at timestamp with time zone); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.signal_source_is_due(p_cadence text, p_last_scanned_at timestamp with time zone) FROM PUBLIC;
GRANT ALL ON FUNCTION public.signal_source_is_due(p_cadence text, p_last_scanned_at timestamp with time zone) TO openclaw_runtime;

--
-- Name: FUNCTION similarity(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.similarity(text, text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.similarity(text, text) TO openclaw_runtime;

--
-- Name: FUNCTION similarity_dist(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.similarity_dist(text, text) FROM PUBLIC;

--
-- Name: FUNCTION similarity_op(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.similarity_op(text, text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.similarity_op(text, text) TO openclaw_runtime;

--
-- Name: FUNCTION strict_word_similarity(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.strict_word_similarity(text, text) FROM PUBLIC;

--
-- Name: FUNCTION strict_word_similarity_commutator_op(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.strict_word_similarity_commutator_op(text, text) FROM PUBLIC;

--
-- Name: FUNCTION strict_word_similarity_dist_commutator_op(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.strict_word_similarity_dist_commutator_op(text, text) FROM PUBLIC;

--
-- Name: FUNCTION strict_word_similarity_dist_op(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.strict_word_similarity_dist_op(text, text) FROM PUBLIC;

--
-- Name: FUNCTION strict_word_similarity_op(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.strict_word_similarity_op(text, text) FROM PUBLIC;

--
-- Name: FUNCTION touch_versioned_row(); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.touch_versioned_row() FROM PUBLIC;

--
-- Name: FUNCTION transition_workflow_run(p_run_id text, p_expected_record_version bigint, p_new_status text, p_flow_revision bigint, p_actor_id text, p_result jsonb, p_error_class text, p_error_message text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.transition_workflow_run(p_run_id text, p_expected_record_version bigint, p_new_status text, p_flow_revision bigint, p_actor_id text, p_result jsonb, p_error_class text, p_error_message text) FROM PUBLIC;
GRANT ALL ON FUNCTION public.transition_workflow_run(p_run_id text, p_expected_record_version bigint, p_new_status text, p_flow_revision bigint, p_actor_id text, p_result jsonb, p_error_class text, p_error_message text) TO openclaw_runtime;

--
-- Name: FUNCTION word_similarity(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.word_similarity(text, text) FROM PUBLIC;

--
-- Name: FUNCTION word_similarity_commutator_op(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.word_similarity_commutator_op(text, text) FROM PUBLIC;

--
-- Name: FUNCTION word_similarity_dist_commutator_op(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.word_similarity_dist_commutator_op(text, text) FROM PUBLIC;

--
-- Name: FUNCTION word_similarity_dist_op(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.word_similarity_dist_op(text, text) FROM PUBLIC;

--
-- Name: FUNCTION word_similarity_op(text, text); Type: ACL; Schema: public; Owner: -
--

REVOKE ALL ON FUNCTION public.word_similarity_op(text, text) FROM PUBLIC;

--
-- Name: SEQUENCE approvals_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.approvals_id_seq TO openclaw_runtime;

--
-- Name: TABLE audit_events; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.audit_events TO openclaw_runtime;

--
-- Name: SEQUENCE audit_events_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.audit_events_id_seq TO openclaw_runtime;

--
-- Name: TABLE channel_principals; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.channel_principals TO openclaw_runtime;

--
-- Name: SEQUENCE channel_principals_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.channel_principals_id_seq TO openclaw_runtime;

--
-- Name: TABLE companies; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.companies TO openclaw_runtime;

--
-- Name: SEQUENCE companies_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.companies_id_seq TO openclaw_runtime;

--
-- Name: TABLE company_aliases; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.company_aliases TO openclaw_runtime;

--
-- Name: SEQUENCE company_aliases_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.company_aliases_id_seq TO openclaw_runtime;

--
-- Name: TABLE company_domains; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.company_domains TO openclaw_runtime;

--
-- Name: SEQUENCE company_domains_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.company_domains_id_seq TO openclaw_runtime;

--
-- Name: TABLE company_external_ids; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.company_external_ids TO openclaw_runtime;

--
-- Name: SEQUENCE company_external_ids_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.company_external_ids_id_seq TO openclaw_runtime;

--
-- Name: TABLE compiled_truth; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.compiled_truth TO openclaw_runtime;

--
-- Name: TABLE compiled_truth_facts; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.compiled_truth_facts TO openclaw_runtime;

--
-- Name: SEQUENCE compiled_truth_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.compiled_truth_id_seq TO openclaw_runtime;

--
-- Name: TABLE contradiction_facts; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.contradiction_facts TO openclaw_runtime;

--
-- Name: TABLE contradictions; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.contradictions TO openclaw_runtime;

--
-- Name: SEQUENCE contradictions_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.contradictions_id_seq TO openclaw_runtime;

--
-- Name: TABLE document_extractions; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.document_extractions TO openclaw_runtime;

--
-- Name: SEQUENCE document_extractions_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.document_extractions_id_seq TO openclaw_runtime;

--
-- Name: TABLE document_facts; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.document_facts TO openclaw_runtime;

--
-- Name: SEQUENCE document_facts_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.document_facts_id_seq TO openclaw_runtime;

--
-- Name: TABLE entity_resolution_consumptions; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.entity_resolution_consumptions TO openclaw_runtime;

--
-- Name: SEQUENCE entity_resolution_consumptions_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.entity_resolution_consumptions_id_seq TO openclaw_runtime;

--
-- Name: TABLE entity_resolution_decisions; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.entity_resolution_decisions TO openclaw_runtime;

--
-- Name: TABLE entity_resolution_runs; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.entity_resolution_runs TO openclaw_runtime;

--
-- Name: TABLE evaluation_criteria; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.evaluation_criteria TO openclaw_runtime;

--
-- Name: TABLE evaluations; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.evaluations TO openclaw_runtime;

--
-- Name: SEQUENCE evaluations_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.evaluations_id_seq TO openclaw_runtime;

--
-- Name: TABLE evidence_artifacts; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.evidence_artifacts TO openclaw_runtime;

--
-- Name: SEQUENCE evidence_artifacts_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.evidence_artifacts_id_seq TO openclaw_runtime;

--
-- Name: TABLE fact_promotion_policy; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.fact_promotion_policy TO openclaw_runtime;

--
-- Name: TABLE fact_sources; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.fact_sources TO openclaw_runtime;

--
-- Name: SEQUENCE fact_sources_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.fact_sources_id_seq TO openclaw_runtime;

--
-- Name: SEQUENCE facts_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.facts_id_seq TO openclaw_runtime;

--
-- Name: TABLE lead_artifacts; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.lead_artifacts TO openclaw_runtime;

--
-- Name: SEQUENCE lead_artifacts_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.lead_artifacts_id_seq TO openclaw_runtime;

--
-- Name: TABLE leads; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.leads TO openclaw_runtime;

--
-- Name: SEQUENCE leads_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.leads_id_seq TO openclaw_runtime;

--
-- Name: TABLE memo_citations; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.memo_citations TO openclaw_runtime;

--
-- Name: TABLE memos; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.memos TO openclaw_runtime;

--
-- Name: SEQUENCE memos_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.memos_id_seq TO openclaw_runtime;

--
-- Name: TABLE notification_attempts; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.notification_attempts TO openclaw_runtime;

--
-- Name: SEQUENCE notification_attempts_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.notification_attempts_id_seq TO openclaw_runtime;

--
-- Name: SEQUENCE notification_outbox_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.notification_outbox_id_seq TO openclaw_runtime;

--
-- Name: TABLE orchestration_audit; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.orchestration_audit TO openclaw_runtime;

--
-- Name: SEQUENCE orchestration_audit_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.orchestration_audit_id_seq TO openclaw_runtime;

--
-- Name: TABLE preference_forget_markers; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.preference_forget_markers TO openclaw_runtime;

--
-- Name: SEQUENCE preference_forget_markers_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.preference_forget_markers_id_seq TO openclaw_runtime;

--
-- Name: TABLE preference_observations; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.preference_observations TO openclaw_runtime;

--
-- Name: SEQUENCE preference_observations_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.preference_observations_id_seq TO openclaw_runtime;

--
-- Name: SEQUENCE proposals_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.proposals_id_seq TO openclaw_runtime;

--
-- Name: TABLE schema_migrations; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.schema_migrations TO openclaw_runtime;

--
-- Name: TABLE signal_sources; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.signal_sources TO openclaw_runtime;

--
-- Name: SEQUENCE signal_sources_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.signal_sources_id_seq TO openclaw_runtime;

--
-- Name: TABLE sources; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.sources TO openclaw_runtime;

--
-- Name: SEQUENCE sources_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.sources_id_seq TO openclaw_runtime;

--
-- Name: TABLE trajectory_events; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.trajectory_events TO openclaw_runtime;

--
-- Name: SEQUENCE trajectory_events_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.trajectory_events_id_seq TO openclaw_runtime;

--
-- Name: TABLE trajectory_points; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.trajectory_points TO openclaw_runtime;

--
-- Name: TABLE trusted_context_uses; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.trusted_context_uses TO openclaw_runtime;

--
-- Name: SEQUENCE trusted_context_uses_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.trusted_context_uses_id_seq TO openclaw_runtime;

--
-- Name: TABLE user_preference_audit; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.user_preference_audit TO openclaw_runtime;

--
-- Name: SEQUENCE user_preference_audit_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.user_preference_audit_id_seq TO openclaw_runtime;

--
-- Name: TABLE user_preferences; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,UPDATE ON TABLE public.user_preferences TO openclaw_runtime;

--
-- Name: TABLE workflow_requests; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.workflow_requests TO openclaw_runtime;

--
-- Name: SEQUENCE workflow_requests_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.workflow_requests_id_seq TO openclaw_runtime;

--
-- Name: SEQUENCE workflow_runs_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.workflow_runs_id_seq TO openclaw_runtime;

--
-- PostgreSQL database dump complete
--

