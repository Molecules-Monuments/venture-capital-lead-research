-- SPDX-License-Identifier: 0BSD
-- OpenClaw Lead Research System 3.0
-- Durable capture of governance proposals. schema-proposal and source-improvement
-- produce reviewed change proposals whose only sink was transient conversation
-- output — silently lost. This persists them for later operator review.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

CREATE TABLE IF NOT EXISTS proposals (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  proposal_kind TEXT NOT NULL CHECK (proposal_kind IN (
    'schema_change', 'source_policy', 'skill_candidate', 'other'
  )),
  title TEXT NOT NULL CHECK (btrim(title) <> ''),
  summary TEXT NOT NULL CHECK (btrim(summary) <> ''),
  lead_id BIGINT REFERENCES leads(id) ON DELETE RESTRICT,
  status TEXT NOT NULL DEFAULT 'submitted'
    CHECK (status IN ('submitted', 'under_review', 'accepted', 'rejected', 'superseded')),
  content JSONB NOT NULL CHECK (jsonb_typeof(content) = 'object'),
  reviewed_by TEXT,
  reviewed_at TIMESTAMPTZ,
  review_note TEXT,
  supersedes_proposal_id BIGINT REFERENCES proposals(id) ON DELETE RESTRICT
    CHECK (supersedes_proposal_id IS NULL OR supersedes_proposal_id <> id),
  created_by TEXT NOT NULL CHECK (btrim(created_by) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  -- A decided proposal must record who decided it.
  CHECK (status NOT IN ('accepted', 'rejected') OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS proposals_status_idx ON proposals (status, created_at DESC);
CREATE INDEX IF NOT EXISTS proposals_kind_idx ON proposals (proposal_kind, created_at DESC);

DROP TRIGGER IF EXISTS proposals_set_updated_at ON proposals;
CREATE TRIGGER proposals_set_updated_at
  BEFORE UPDATE ON proposals
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- The runtime records proposals (agent-triggered submission) and reads them,
-- and keeps UPDATE so an agent workflow can move submitted -> under_review.
-- Decision transitions (accepted/rejected) are enforced at the database
-- boundary: the guard trigger below rejects any INSERT born decided and any
-- UPDATE that enters a decided status unless it runs with the table owner's
-- authority — i.e. through the SECURITY DEFINER decide_proposal function —
-- and decided proposals are immutable to the runtime role.
REVOKE ALL ON proposals FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON proposals TO openclaw_runtime;
GRANT USAGE, SELECT ON SEQUENCE proposals_id_seq TO openclaw_runtime;

CREATE OR REPLACE FUNCTION guard_proposal_decision()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog, public
AS $function$
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
$function$;

DROP TRIGGER IF EXISTS proposals_guard_decision ON proposals;
CREATE TRIGGER proposals_guard_decision
  BEFORE INSERT OR UPDATE ON proposals
  FOR EACH ROW EXECUTE FUNCTION guard_proposal_decision();

-- Audited operator-lane decision path. SECURITY DEFINER (table-owner
-- authority) is what satisfies the guard above; the helper additionally
-- gates this behind its authenticated operator-only runtime.
CREATE OR REPLACE FUNCTION decide_proposal(
  p_proposal_id BIGINT,
  p_decision TEXT,
  p_reviewed_by TEXT,
  p_review_note TEXT,
  p_actor_id TEXT
)
RETURNS SETOF proposals
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
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
$function$;

REVOKE ALL ON FUNCTION decide_proposal(BIGINT, TEXT, TEXT, TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION decide_proposal(BIGINT, TEXT, TEXT, TEXT, TEXT) TO openclaw_runtime;

COMMIT;
