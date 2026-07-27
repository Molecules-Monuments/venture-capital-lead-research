-- OpenClaw Lead Research System 3.0
-- Verified channel principals, replay-protected capabilities, and bounded preferences.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

CREATE TABLE IF NOT EXISTS channel_principals (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  provider TEXT NOT NULL CHECK (provider IN ('slack','msteams','discord','telegram')),
  account_id TEXT NOT NULL CHECK (btrim(account_id) <> ''),
  sender_id TEXT NOT NULL CHECK (btrim(sender_id) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (provider,account_id,sender_id)
);

CREATE TABLE IF NOT EXISTS trusted_context_uses (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  principal_id BIGINT NOT NULL REFERENCES channel_principals(id) ON DELETE RESTRICT,
  nonce TEXT NOT NULL CHECK (nonce ~ '^[0-9a-f]{48}$'),
  scope TEXT NOT NULL CHECK (btrim(scope) <> ''),
  operation_key TEXT NOT NULL CHECK (btrim(operation_key) <> ''),
  event_id TEXT NOT NULL CHECK (btrim(event_id) <> ''),
  run_id TEXT NOT NULL CHECK (btrim(run_id) <> ''),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (nonce,scope)
);

CREATE TABLE IF NOT EXISTS preference_observations (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  principal_id BIGINT NOT NULL REFERENCES channel_principals(id) ON DELETE RESTRICT,
  preference_key TEXT NOT NULL CHECK (preference_key IN (
    'memo_length','communication_tone','research_depth','citation_density','output_structure'
  )),
  preference_value TEXT NOT NULL CHECK (btrim(preference_value) <> ''),
  observation_kind TEXT NOT NULL CHECK (observation_kind IN ('explicit','inferred')),
  event_id TEXT NOT NULL CHECK (btrim(event_id) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (principal_id,preference_key,preference_value,event_id)
);

CREATE TABLE IF NOT EXISTS user_preferences (
  principal_id BIGINT NOT NULL REFERENCES channel_principals(id) ON DELETE RESTRICT,
  preference_key TEXT NOT NULL CHECK (preference_key IN (
    'memo_length','communication_tone','research_depth','citation_density','output_structure'
  )),
  preference_value TEXT,
  source_kind TEXT CHECK (source_kind IN ('explicit','inferred')),
  evidence_count INTEGER NOT NULL DEFAULT 0 CHECK (evidence_count >= 0),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','forgotten')),
  source_event_id TEXT,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (principal_id,preference_key),
  CHECK (
    (status='active' AND preference_value IS NOT NULL AND source_kind IS NOT NULL AND source_event_id IS NOT NULL)
    OR (status='forgotten' AND preference_value IS NULL AND source_kind IS NULL AND source_event_id IS NULL)
  )
);

CREATE TABLE IF NOT EXISTS preference_forget_markers (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  principal_id BIGINT NOT NULL REFERENCES channel_principals(id) ON DELETE RESTRICT,
  preference_key TEXT NOT NULL CHECK (preference_key IN (
    'memo_length','communication_tone','research_depth','citation_density','output_structure'
  )),
  event_id TEXT NOT NULL CHECK (btrim(event_id) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (principal_id,preference_key,event_id)
);

CREATE TABLE IF NOT EXISTS user_preference_audit (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  principal_id BIGINT NOT NULL REFERENCES channel_principals(id) ON DELETE RESTRICT,
  preference_key TEXT,
  action TEXT NOT NULL CHECK (action IN ('activated','superseded','forgotten')),
  source_kind TEXT CHECK (source_kind IN ('explicit','inferred')),
  event_id TEXT NOT NULL CHECK (btrim(event_id) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (principal_id,preference_key,action,event_id)
);

CREATE INDEX IF NOT EXISTS trusted_context_uses_principal_idx ON trusted_context_uses(principal_id,used_at DESC);
CREATE INDEX IF NOT EXISTS preference_observations_activation_idx
  ON preference_observations(principal_id,preference_key,preference_value,observation_kind);
CREATE INDEX IF NOT EXISTS preference_forget_markers_cutoff_idx
  ON preference_forget_markers(principal_id,preference_key,created_at DESC);

DROP TRIGGER IF EXISTS trusted_context_uses_append_only ON trusted_context_uses;
CREATE TRIGGER trusted_context_uses_append_only
  BEFORE UPDATE OR DELETE ON trusted_context_uses
  FOR EACH ROW EXECUTE FUNCTION prevent_domain_history_mutation();
DROP TRIGGER IF EXISTS preference_observations_append_only ON preference_observations;
CREATE TRIGGER preference_observations_append_only
  BEFORE UPDATE OR DELETE ON preference_observations
  FOR EACH ROW EXECUTE FUNCTION prevent_domain_history_mutation();
DROP TRIGGER IF EXISTS preference_forget_markers_append_only ON preference_forget_markers;
CREATE TRIGGER preference_forget_markers_append_only
  BEFORE UPDATE OR DELETE ON preference_forget_markers
  FOR EACH ROW EXECUTE FUNCTION prevent_domain_history_mutation();
DROP TRIGGER IF EXISTS user_preference_audit_append_only ON user_preference_audit;
CREATE TRIGGER user_preference_audit_append_only
  BEFORE UPDATE OR DELETE ON user_preference_audit
  FOR EACH ROW EXECUTE FUNCTION prevent_domain_history_mutation();

REVOKE ALL ON channel_principals,trusted_context_uses,preference_observations,user_preferences,
  preference_forget_markers,user_preference_audit FROM PUBLIC;
GRANT SELECT,INSERT,UPDATE ON channel_principals TO openclaw_runtime;
GRANT SELECT,INSERT ON trusted_context_uses,preference_observations,preference_forget_markers,
  user_preference_audit TO openclaw_runtime;
GRANT SELECT,INSERT,UPDATE ON user_preferences TO openclaw_runtime;
GRANT USAGE,SELECT ON SEQUENCE channel_principals_id_seq,trusted_context_uses_id_seq,
  preference_observations_id_seq,preference_forget_markers_id_seq,user_preference_audit_id_seq
  TO openclaw_runtime;

COMMIT;
