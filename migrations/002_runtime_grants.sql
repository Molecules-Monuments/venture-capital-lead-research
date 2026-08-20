-- SPDX-License-Identifier: Apache-2.0
-- Venture Capital Lead Research System 2.0
-- Least-privilege grants for the trusted vcops runtime role.
-- Apply as openclaw_owner after 001_initial_v2.sql and 000_roles.sh.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '60s';

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

DO $block$
BEGIN
  EXECUTE format('REVOKE TEMPORARY ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('REVOKE CREATE ON DATABASE %I FROM PUBLIC', current_database());
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO openclaw_runtime', current_database());
END;
$block$;

REVOKE ALL ON SCHEMA public FROM openclaw_runtime;
GRANT USAGE ON SCHEMA public TO openclaw_runtime;

-- Migration records are installer-owned and append-only.
REVOKE ALL ON schema_migrations FROM openclaw_runtime;
GRANT SELECT ON schema_migrations TO openclaw_runtime;

-- The runtime can append and maintain typed domain state, but cannot delete,
-- truncate, alter, create, own, or grant database objects.
GRANT SELECT, INSERT, UPDATE ON
  companies,
  leads,
  sources,
  evidence_artifacts,
  lead_artifacts,
  document_extractions,
  facts,
  fact_sources,
  document_facts,
  compiled_truth,
  compiled_truth_facts,
  contradictions,
  contradiction_facts,
  trajectory_events,
  trajectory_points,
  evaluations,
  evaluation_criteria,
  memos
TO openclaw_runtime;

-- Sensitive lifecycle rows are appendable/readable through ordinary SQL but
-- mutable only through the reviewed SECURITY DEFINER APIs below.
GRANT SELECT, INSERT ON
  workflow_runs,
  approvals,
  notification_outbox
TO openclaw_runtime;
GRANT SELECT ON notification_attempts TO openclaw_runtime;

-- Audit is append-only both by privilege and by owner-level trigger.
REVOKE ALL ON audit_events FROM openclaw_runtime;
GRANT SELECT, INSERT ON audit_events TO openclaw_runtime;

GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO openclaw_runtime;

GRANT EXECUTE ON FUNCTION transition_workflow_run(
  TEXT, BIGINT, TEXT, BIGINT, TEXT, JSONB, TEXT, TEXT
) TO openclaw_runtime;
GRANT EXECUTE ON FUNCTION request_workflow_cancel(TEXT, BIGINT, TEXT, TEXT)
TO openclaw_runtime;
GRANT EXECUTE ON FUNCTION decide_approval(
  TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO openclaw_runtime;
GRANT EXECUTE ON FUNCTION consume_approval(
  TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT
) TO openclaw_runtime;
GRANT EXECUTE ON FUNCTION claim_notification(TEXT, INTEGER) TO openclaw_runtime;
GRANT EXECUTE ON FUNCTION finish_notification_attempt(
  BIGINT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER
) TO openclaw_runtime;
GRANT EXECUTE ON FUNCTION release_held_notification(BIGINT, TEXT) TO openclaw_runtime;
GRANT EXECUTE ON FUNCTION cancel_notification(BIGINT, TEXT) TO openclaw_runtime;

-- A later migration is not implicitly exposed to the runtime. Its installer
-- must add deliberate grants after review.
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM PUBLIC;

COMMIT;
