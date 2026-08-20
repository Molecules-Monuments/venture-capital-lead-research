-- SPDX-License-Identifier: Apache-2.0
-- Venture Capital Lead Research System 2.0
-- Initial PostgreSQL 17 schema. Apply as openclaw_owner.
-- The migration is additive and safe to re-run against a schema it created.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';
SET LOCAL client_min_messages = warning;

CREATE TABLE IF NOT EXISTS schema_migrations (
  version TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  checksum_sha256 TEXT NOT NULL CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
  applied_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION register_schema_migration(
  p_version TEXT,
  p_name TEXT,
  p_checksum_sha256 TEXT
)
RETURNS VOID
LANGUAGE plpgsql
AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
BEGIN
  NEW.updated_at := clock_timestamp();
  RETURN NEW;
END;
$function$;

CREATE OR REPLACE FUNCTION touch_versioned_row()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
BEGIN
  NEW.updated_at := clock_timestamp();
  NEW.row_version := OLD.row_version + 1;
  RETURN NEW;
END;
$function$;

CREATE TABLE IF NOT EXISTS companies (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name TEXT NOT NULL CHECK (btrim(name) <> ''),
  legal_name TEXT,
  canonical_domain TEXT,
  website_uri TEXT,
  sector TEXT,
  geography TEXT,
  stage_estimate TEXT,
  one_line_description TEXT,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'inactive', 'acquired', 'closed', 'merged', 'unknown')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(metadata) = 'object'),
  row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (canonical_domain IS NULL OR canonical_domain = lower(btrim(canonical_domain))),
  CHECK (canonical_domain IS NULL OR canonical_domain !~ '[/@:]')
);

CREATE UNIQUE INDEX IF NOT EXISTS companies_canonical_domain_uidx
  ON companies (canonical_domain) WHERE canonical_domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS companies_name_lower_idx ON companies (lower(name));

CREATE TABLE IF NOT EXISTS leads (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id BIGINT REFERENCES companies(id) ON DELETE RESTRICT,
  lead_title TEXT NOT NULL CHECK (btrim(lead_title) <> ''),
  origin_group TEXT NOT NULL DEFAULT 'unspecified'
    CHECK (origin_group IN ('outbound', 'inbound', 'unspecified')),
  origin_subtype TEXT NOT NULL DEFAULT 'unknown' CHECK (btrim(origin_subtype) <> ''),
  origin_confidence TEXT NOT NULL DEFAULT 'low'
    CHECK (origin_confidence IN ('low', 'medium', 'high')),
  origin_note TEXT,
  intake_channel TEXT,
  channel_provider TEXT,
  channel_account_id TEXT,
  channel_event_id TEXT,
  channel_message_id TEXT,
  channel_sender_id TEXT,
  channel_permalink TEXT,
  source_trust_level TEXT NOT NULL DEFAULT 'unknown'
    CHECK (source_trust_level IN (
      'internal_admin', 'allowlisted_operator', 'remote_channel', 'public_web',
      'paid_connector', 'untrusted_upload', 'generated_internal', 'unknown'
    )),
  confidentiality TEXT NOT NULL DEFAULT 'internal'
    CHECK (confidentiality IN ('public', 'internal', 'confidential', 'restricted')),
  referrer_name TEXT,
  referrer_organization TEXT,
  submitted_by TEXT,
  owner_id TEXT,
  status TEXT NOT NULL DEFAULT 'new'
    CHECK (status IN (
      'new', 'triaged', 'needs_review', 'researching', 'watch', 'passed',
      'research_deeper', 'high_priority', 'rejected', 'archived'
    )),
  priority TEXT NOT NULL DEFAULT 'unassigned'
    CHECK (priority IN ('unassigned', 'low', 'medium', 'high', 'urgent')),
  thesis_version TEXT,
  missing_fields JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(missing_fields) = 'array'),
  submitted_claims JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(submitted_claims) = 'object'),
  idempotency_key TEXT NOT NULL CHECK (btrim(idempotency_key) <> ''),
  row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (idempotency_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS leads_provider_event_uidx
  ON leads (channel_provider, channel_account_id, channel_event_id)
  WHERE channel_provider IS NOT NULL
    AND channel_account_id IS NOT NULL
    AND channel_event_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS leads_company_status_idx ON leads (company_id, status);
CREATE INDEX IF NOT EXISTS leads_created_at_idx ON leads (created_at DESC);

CREATE TABLE IF NOT EXISTS sources (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_kind TEXT NOT NULL
    CHECK (source_kind IN (
      'primary_document', 'company_website', 'regulatory_filing', 'channel_message',
      'public_web', 'paid_connector', 'operator_statement', 'internal_analysis',
      'provider_event', 'other'
    )),
  title TEXT,
  canonical_uri TEXT,
  provider TEXT,
  provider_account_id TEXT,
  stable_source_id TEXT,
  trust_level TEXT NOT NULL DEFAULT 'unknown'
    CHECK (trust_level IN (
      'internal_admin', 'allowlisted_operator', 'remote_channel', 'public_web',
      'paid_connector', 'untrusted_upload', 'generated_internal', 'unknown'
    )),
  confidentiality TEXT NOT NULL DEFAULT 'internal'
    CHECK (confidentiality IN ('public', 'internal', 'confidential', 'restricted')),
  publisher TEXT,
  author_label TEXT,
  published_at TIMESTAMPTZ,
  accessed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  content_sha256 TEXT CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (canonical_uri IS NOT NULL OR stable_source_id IS NOT NULL),
  CHECK (stable_source_id IS NULL OR provider IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS sources_provider_stable_uidx
  ON sources (provider, provider_account_id, stable_source_id)
  NULLS NOT DISTINCT
  WHERE stable_source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS sources_canonical_uri_idx
  ON sources (canonical_uri) WHERE canonical_uri IS NOT NULL;
CREATE INDEX IF NOT EXISTS sources_published_at_idx ON sources (published_at DESC);

-- Content identity is global. Lead provenance belongs in lead_artifacts.
CREATE TABLE IF NOT EXISTS evidence_artifacts (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  sha256 TEXT NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  artifact_type TEXT NOT NULL
    CHECK (artifact_type IN (
      'channel_message', 'document', 'url_capture', 'connector_export', 'memo',
      'report', 'internal_note', 'extracted_text', 'structured_data', 'other'
    )),
  storage_tier TEXT NOT NULL
    CHECK (storage_tier IN (
      'workspace_file', 'object_store', 'postgres_row', 'external_reference', 'quarantine'
    )),
  trust_boundary TEXT NOT NULL
    CHECK (trust_boundary IN (
      'internal_admin', 'allowlisted_operator', 'remote_channel', 'public_web',
      'paid_connector', 'untrusted_upload', 'generated_internal', 'unknown'
    )),
  confidentiality TEXT NOT NULL DEFAULT 'internal'
    CHECK (confidentiality IN ('public', 'internal', 'confidential', 'restricted')),
  retention_class TEXT NOT NULL DEFAULT 'standard'
    CHECK (retention_class IN ('short', 'standard', 'long', 'legal_hold', 'delete_after_review')),
  storage_uri TEXT,
  external_uri TEXT,
  mime_type TEXT,
  size_bytes BIGINT CHECK (size_bytes IS NULL OR size_bytes >= 0),
  content_encoding TEXT,
  collected_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (sha256),
  CHECK (storage_uri IS NOT NULL OR external_uri IS NOT NULL OR storage_tier = 'postgres_row')
);

CREATE INDEX IF NOT EXISTS evidence_artifacts_type_idx
  ON evidence_artifacts (artifact_type, collected_at DESC);
CREATE INDEX IF NOT EXISTS evidence_artifacts_retention_idx
  ON evidence_artifacts (retention_class, created_at);

CREATE TABLE IF NOT EXISTS lead_artifacts (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
  artifact_id BIGINT NOT NULL REFERENCES evidence_artifacts(id) ON DELETE RESTRICT,
  source_id BIGINT REFERENCES sources(id) ON DELETE RESTRICT,
  association_role TEXT NOT NULL DEFAULT 'evidence'
    CHECK (association_role IN (
      'submission', 'evidence', 'contradicting_evidence', 'context', 'generated_output'
    )),
  original_filename TEXT,
  source_locator TEXT,
  submitted_by TEXT,
  received_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  provenance JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(provenance) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (lead_id, artifact_id)
);

CREATE INDEX IF NOT EXISTS lead_artifacts_artifact_idx ON lead_artifacts (artifact_id, lead_id);
CREATE INDEX IF NOT EXISTS lead_artifacts_source_idx
  ON lead_artifacts (source_id) WHERE source_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS workflow_runs (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  run_id TEXT NOT NULL CHECK (btrim(run_id) <> ''),
  workflow_id TEXT NOT NULL CHECK (btrim(workflow_id) <> ''),
  workflow_version TEXT,
  lead_id BIGINT REFERENCES leads(id) ON DELETE RESTRICT,
  company_id BIGINT REFERENCES companies(id) ON DELETE RESTRICT,
  parent_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  external_flow_id TEXT,
  idempotency_key TEXT NOT NULL CHECK (btrim(idempotency_key) <> ''),
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN (
      'queued', 'started', 'running', 'waiting', 'blocked',
      'succeeded', 'failed', 'cancelled', 'lost'
    )),
  flow_revision BIGINT NOT NULL DEFAULT 0 CHECK (flow_revision >= 0),
  record_version BIGINT NOT NULL DEFAULT 1 CHECK (record_version > 0),
  input_hash TEXT CHECK (input_hash IS NULL OR input_hash ~ '^[0-9a-f]{64}$'),
  policy_version TEXT,
  requested_by TEXT,
  started_at TIMESTAMPTZ,
  heartbeat_at TIMESTAMPTZ,
  waiting_reason TEXT,
  blocked_reason TEXT,
  cancel_requested_at TIMESTAMPTZ,
  cancelled_by TEXT,
  cancellation_reason TEXT,
  finished_at TIMESTAMPTZ,
  error_class TEXT,
  error_message TEXT,
  result JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(result) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (run_id),
  UNIQUE (workflow_id, idempotency_key),
  CHECK (lead_id IS NOT NULL OR company_id IS NOT NULL OR workflow_id LIKE 'system.%'),
  CHECK (status <> 'cancelled' OR cancel_requested_at IS NOT NULL),
  CHECK (status NOT IN ('succeeded', 'failed', 'cancelled', 'lost') OR finished_at IS NOT NULL),
  CHECK (status <> 'failed' OR error_class IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS workflow_runs_active_idx
  ON workflow_runs (status, heartbeat_at)
  WHERE status IN ('queued', 'started', 'running', 'waiting', 'blocked');
CREATE INDEX IF NOT EXISTS workflow_runs_external_flow_idx
  ON workflow_runs (external_flow_id) WHERE external_flow_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS workflow_runs_lead_idx ON workflow_runs (lead_id, created_at DESC);

CREATE TABLE IF NOT EXISTS document_extractions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  artifact_id BIGINT NOT NULL REFERENCES evidence_artifacts(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  extractor_name TEXT NOT NULL CHECK (btrim(extractor_name) <> ''),
  extractor_version TEXT NOT NULL CHECK (btrim(extractor_version) <> ''),
  idempotency_key TEXT NOT NULL CHECK (btrim(idempotency_key) <> ''),
  status TEXT NOT NULL DEFAULT 'queued'
    CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'quarantined', 'unsupported')),
  output_uri TEXT,
  extracted_sha256 TEXT CHECK (extracted_sha256 IS NULL OR extracted_sha256 ~ '^[0-9a-f]{64}$'),
  detected_mime_type TEXT,
  page_count INTEGER CHECK (page_count IS NULL OR page_count >= 0),
  sheet_count INTEGER CHECK (sheet_count IS NULL OR sheet_count >= 0),
  row_count BIGINT CHECK (row_count IS NULL OR row_count >= 0),
  character_count BIGINT CHECK (character_count IS NULL OR character_count >= 0),
  contains_formulas BOOLEAN NOT NULL DEFAULT false,
  safety_findings JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(safety_findings) = 'array'),
  extraction_summary JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(extraction_summary) = 'object'),
  error_class TEXT,
  error_message TEXT,
  started_at TIMESTAMPTZ,
  finished_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (artifact_id, extractor_name, extractor_version, idempotency_key),
  CHECK (status <> 'succeeded' OR (output_uri IS NOT NULL AND extracted_sha256 IS NOT NULL)),
  CHECK (status <> 'failed' OR error_class IS NOT NULL),
  CHECK (status NOT IN ('succeeded', 'failed', 'quarantined', 'unsupported') OR finished_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS document_extractions_status_idx
  ON document_extractions (status, created_at);

CREATE TABLE IF NOT EXISTS facts (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  lead_id BIGINT REFERENCES leads(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  fact_type TEXT NOT NULL CHECK (btrim(fact_type) <> ''),
  definition TEXT NOT NULL CHECK (btrim(definition) <> ''),
  definition_version TEXT NOT NULL DEFAULT '1',
  value_kind TEXT NOT NULL
    CHECK (value_kind IN ('text', 'numeric', 'boolean', 'date', 'json', 'unknown')),
  original_value TEXT,
  value_text TEXT,
  value_numeric NUMERIC,
  value_boolean BOOLEAN,
  value_date DATE,
  value_json JSONB,
  unit TEXT,
  currency_code TEXT CHECK (currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'),
  period_start DATE,
  period_end DATE,
  period_granularity TEXT
    CHECK (period_granularity IS NULL OR period_granularity IN (
      'instant', 'day', 'week', 'month', 'quarter', 'year', 'lifetime', 'unknown'
    )),
  cohort TEXT,
  measurement_basis TEXT,
  fact_status TEXT NOT NULL DEFAULT 'submitted_claim'
    CHECK (fact_status IN (
      'submitted_claim', 'verified_fact', 'derived_inference', 'contradicted',
      'stale', 'retracted', 'unknown'
    )),
  confidence NUMERIC(4,3) NOT NULL DEFAULT 0.000
    CHECK (confidence >= 0 AND confidence <= 1),
  observed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  source_date DATE,
  valid_from DATE,
  valid_to DATE,
  supersedes_fact_id BIGINT REFERENCES facts(id) ON DELETE RESTRICT,
  version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
  created_by TEXT NOT NULL CHECK (btrim(created_by) <> ''),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (period_end IS NULL OR period_start IS NULL OR period_end >= period_start),
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
  CHECK (supersedes_fact_id IS NULL OR supersedes_fact_id <> id),
  CHECK (
    (value_kind = 'text' AND value_text IS NOT NULL AND value_numeric IS NULL AND value_boolean IS NULL AND value_date IS NULL AND value_json IS NULL) OR
    (value_kind = 'numeric' AND value_text IS NULL AND value_numeric IS NOT NULL AND value_boolean IS NULL AND value_date IS NULL AND value_json IS NULL) OR
    (value_kind = 'boolean' AND value_text IS NULL AND value_numeric IS NULL AND value_boolean IS NOT NULL AND value_date IS NULL AND value_json IS NULL) OR
    (value_kind = 'date' AND value_text IS NULL AND value_numeric IS NULL AND value_boolean IS NULL AND value_date IS NOT NULL AND value_json IS NULL) OR
    (value_kind = 'json' AND value_text IS NULL AND value_numeric IS NULL AND value_boolean IS NULL AND value_date IS NULL AND value_json IS NOT NULL) OR
    (value_kind = 'unknown' AND value_text IS NULL AND value_numeric IS NULL AND value_boolean IS NULL AND value_date IS NULL AND value_json IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS facts_definition_time_idx
  ON facts (company_id, fact_type, definition, period_start, period_end, observed_at DESC);
CREATE INDEX IF NOT EXISTS facts_lead_status_idx ON facts (lead_id, fact_status);
CREATE INDEX IF NOT EXISTS facts_supersedes_idx
  ON facts (supersedes_fact_id) WHERE supersedes_fact_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS fact_sources (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fact_id BIGINT NOT NULL REFERENCES facts(id) ON DELETE RESTRICT,
  source_id BIGINT NOT NULL REFERENCES sources(id) ON DELETE RESTRICT,
  artifact_id BIGINT REFERENCES evidence_artifacts(id) ON DELETE RESTRICT,
  extraction_id BIGINT REFERENCES document_extractions(id) ON DELETE RESTRICT,
  evidence_role TEXT NOT NULL DEFAULT 'primary'
    CHECK (evidence_role IN ('primary', 'supporting', 'contradicting', 'context')),
  citation_label TEXT,
  source_locator TEXT,
  quoted_text_hash TEXT CHECK (quoted_text_hash IS NULL OR quoted_text_hash ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE NULLS NOT DISTINCT (fact_id, source_id, artifact_id, extraction_id, evidence_role),
  CHECK (artifact_id IS NOT NULL OR extraction_id IS NULL)
);

CREATE INDEX IF NOT EXISTS fact_sources_source_idx ON fact_sources (source_id, fact_id);
CREATE INDEX IF NOT EXISTS fact_sources_artifact_idx
  ON fact_sources (artifact_id) WHERE artifact_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS document_facts (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  extraction_id BIGINT NOT NULL REFERENCES document_extractions(id) ON DELETE RESTRICT,
  fact_id BIGINT NOT NULL REFERENCES facts(id) ON DELETE RESTRICT,
  page_number INTEGER CHECK (page_number IS NULL OR page_number > 0),
  sheet_name TEXT,
  cell_range TEXT,
  paragraph_number INTEGER CHECK (paragraph_number IS NULL OR paragraph_number > 0),
  source_locator TEXT,
  locator_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(locator_metadata) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE NULLS NOT DISTINCT (
    extraction_id, fact_id, page_number, sheet_name, cell_range, paragraph_number
  )
);

CREATE INDEX IF NOT EXISTS document_facts_fact_idx ON document_facts (fact_id);

CREATE TABLE IF NOT EXISTS compiled_truth (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  prior_snapshot_id BIGINT REFERENCES compiled_truth(id) ON DELETE RESTRICT,
  snapshot_version INTEGER NOT NULL CHECK (snapshot_version > 0),
  policy_version TEXT NOT NULL CHECK (btrim(policy_version) <> ''),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'current', 'superseded', 'stale', 'invalid')),
  current_view JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(current_view) = 'object'),
  coverage JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(coverage) = 'object'),
  coverage_percent NUMERIC(5,2) NOT NULL DEFAULT 0
    CHECK (coverage_percent >= 0 AND coverage_percent <= 100),
  evidence_timeline JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(evidence_timeline) = 'array'),
  missing_data JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(missing_data) = 'array'),
  material_delta JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(material_delta) = 'object'),
  evidence_packet_hash TEXT NOT NULL CHECK (evidence_packet_hash ~ '^[0-9a-f]{64}$'),
  compiled_by TEXT NOT NULL CHECK (btrim(compiled_by) <> ''),
  compiled_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  stale_after TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (lead_id, snapshot_version),
  UNIQUE (lead_id, evidence_packet_hash),
  CHECK (prior_snapshot_id IS NULL OR prior_snapshot_id <> id),
  CHECK (stale_after IS NULL OR stale_after > compiled_at)
);

CREATE UNIQUE INDEX IF NOT EXISTS compiled_truth_one_current_uidx
  ON compiled_truth (lead_id) WHERE status = 'current';
CREATE INDEX IF NOT EXISTS compiled_truth_company_idx
  ON compiled_truth (company_id, compiled_at DESC);

CREATE TABLE IF NOT EXISTS compiled_truth_facts (
  compiled_truth_id BIGINT NOT NULL REFERENCES compiled_truth(id) ON DELETE RESTRICT,
  fact_id BIGINT NOT NULL REFERENCES facts(id) ON DELETE RESTRICT,
  support_role TEXT NOT NULL
    CHECK (support_role IN ('current', 'historical', 'contradicted', 'stale', 'missing_context')),
  claim_path TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (compiled_truth_id, fact_id, support_role)
);

CREATE INDEX IF NOT EXISTS compiled_truth_facts_fact_idx ON compiled_truth_facts (fact_id);

CREATE TABLE IF NOT EXISTS contradictions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  finding_kind TEXT NOT NULL
    CHECK (finding_kind IN (
      'contradiction', 'ordinary_change', 'superseded', 'stale',
      'not_comparable', 'identity_conflict'
    )),
  severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'blocking')),
  status TEXT NOT NULL DEFAULT 'open'
    CHECK (status IN ('open', 'under_review', 'resolved', 'accepted_risk', 'dismissed')),
  fact_type TEXT NOT NULL,
  definition TEXT NOT NULL,
  normalized_unit TEXT,
  normalized_currency_code TEXT
    CHECK (normalized_currency_code IS NULL OR normalized_currency_code ~ '^[A-Z]{3}$'),
  measurement_basis TEXT,
  cohort TEXT,
  overlap_start DATE,
  overlap_end DATE,
  normalization JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(normalization) = 'object'),
  explanation TEXT NOT NULL CHECK (btrim(explanation) <> ''),
  resolution_note TEXT,
  reviewed_by TEXT,
  reviewed_at TIMESTAMPTZ,
  created_by TEXT NOT NULL CHECK (btrim(created_by) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (overlap_end IS NULL OR overlap_start IS NULL OR overlap_end >= overlap_start),
  CHECK (status NOT IN ('resolved', 'accepted_risk', 'dismissed') OR reviewed_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS contradictions_open_idx
  ON contradictions (lead_id, severity)
  WHERE status IN ('open', 'under_review');

CREATE TABLE IF NOT EXISTS contradiction_facts (
  contradiction_id BIGINT NOT NULL REFERENCES contradictions(id) ON DELETE RESTRICT,
  fact_id BIGINT NOT NULL REFERENCES facts(id) ON DELETE RESTRICT,
  assertion_role TEXT NOT NULL
    CHECK (assertion_role IN ('left', 'right', 'supporting', 'resolution')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (contradiction_id, fact_id, assertion_role)
);

CREATE INDEX IF NOT EXISTS contradiction_facts_fact_idx ON contradiction_facts (fact_id);

CREATE TABLE IF NOT EXISTS trajectory_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  fact_type TEXT NOT NULL CHECK (btrim(fact_type) <> ''),
  definition TEXT NOT NULL CHECK (btrim(definition) <> ''),
  direction TEXT NOT NULL
    CHECK (direction IN ('up', 'down', 'flat', 'volatile', 'unknown_baseline', 'not_comparable')),
  status TEXT NOT NULL DEFAULT 'current'
    CHECK (status IN ('current', 'superseded', 'invalid')),
  normalized_unit TEXT,
  normalized_currency_code TEXT
    CHECK (normalized_currency_code IS NULL OR normalized_currency_code ~ '^[A-Z]{3}$'),
  measurement_basis TEXT,
  cohort TEXT,
  point_count INTEGER NOT NULL CHECK (point_count > 0),
  calculation JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(calculation) = 'object'),
  score_adjustment NUMERIC(4,2) NOT NULL DEFAULT 0
    CHECK (score_adjustment >= -5 AND score_adjustment <= 5),
  policy_version TEXT NOT NULL,
  calculated_by TEXT NOT NULL,
  calculated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (point_count >= 2 OR direction IN ('unknown_baseline', 'not_comparable')),
  CHECK (direction <> 'not_comparable' OR score_adjustment = 0)
);

CREATE INDEX IF NOT EXISTS trajectory_events_lead_idx
  ON trajectory_events (lead_id, fact_type, calculated_at DESC);

CREATE TABLE IF NOT EXISTS trajectory_points (
  trajectory_event_id BIGINT NOT NULL REFERENCES trajectory_events(id) ON DELETE RESTRICT,
  fact_id BIGINT NOT NULL REFERENCES facts(id) ON DELETE RESTRICT,
  point_order INTEGER NOT NULL CHECK (point_order > 0),
  normalized_value NUMERIC,
  effective_at DATE NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (trajectory_event_id, point_order),
  UNIQUE (trajectory_event_id, fact_id)
);

CREATE INDEX IF NOT EXISTS trajectory_points_fact_idx ON trajectory_points (fact_id);

CREATE TABLE IF NOT EXISTS evaluations (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  compiled_truth_id BIGINT NOT NULL REFERENCES compiled_truth(id) ON DELETE RESTRICT,
  evaluation_version INTEGER NOT NULL CHECK (evaluation_version > 0),
  rubric_version TEXT NOT NULL CHECK (btrim(rubric_version) <> ''),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'final', 'superseded', 'invalid')),
  fixed_denominator NUMERIC(5,2) NOT NULL DEFAULT 100
    CHECK (fixed_denominator = 100),
  total_score NUMERIC(5,2) NOT NULL CHECK (total_score >= 0 AND total_score <= 100),
  display_score NUMERIC(3,2) NOT NULL CHECK (display_score >= 0 AND display_score <= 5),
  recommendation_band TEXT NOT NULL
    CHECK (recommendation_band IN ('pass', 'watch', 'research_deeper', 'high_priority')),
  evidence_coverage_percent NUMERIC(5,2) NOT NULL
    CHECK (evidence_coverage_percent >= 0 AND evidence_coverage_percent <= 100),
  confidence NUMERIC(4,3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
  missing_criteria JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(missing_criteria) = 'array'),
  blockers JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(blockers) = 'array'),
  scoring_details JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(scoring_details) = 'object'),
  evidence_packet_hash TEXT NOT NULL CHECK (evidence_packet_hash ~ '^[0-9a-f]{64}$'),
  evaluated_by TEXT NOT NULL,
  evaluated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (lead_id, evaluation_version),
  UNIQUE (lead_id, evidence_packet_hash, rubric_version),
  CHECK (
    (total_score >= 0 AND total_score < 50 AND recommendation_band = 'pass') OR
    (total_score >= 50 AND total_score < 66 AND recommendation_band = 'watch') OR
    (total_score >= 66 AND total_score < 82 AND recommendation_band = 'research_deeper') OR
    (total_score >= 82 AND total_score <= 100 AND recommendation_band = 'high_priority')
  )
);

CREATE UNIQUE INDEX IF NOT EXISTS evaluations_one_final_uidx
  ON evaluations (lead_id) WHERE status = 'final';
CREATE INDEX IF NOT EXISTS evaluations_band_idx
  ON evaluations (recommendation_band, evaluated_at DESC) WHERE status = 'final';

CREATE TABLE IF NOT EXISTS evaluation_criteria (
  evaluation_id BIGINT NOT NULL REFERENCES evaluations(id) ON DELETE RESTRICT,
  criterion_key TEXT NOT NULL CHECK (btrim(criterion_key) <> ''),
  criterion_score NUMERIC(3,2) NOT NULL CHECK (criterion_score >= 0 AND criterion_score <= 5),
  weight_points NUMERIC(5,2) NOT NULL CHECK (weight_points >= 0 AND weight_points <= 100),
  weighted_points NUMERIC(5,2) NOT NULL CHECK (weighted_points >= 0 AND weighted_points <= 100),
  is_missing BOOLEAN NOT NULL DEFAULT false,
  rationale TEXT NOT NULL,
  evidence_fact_ids JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(evidence_fact_ids) = 'array'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (evaluation_id, criterion_key),
  CHECK (NOT is_missing OR (criterion_score = 0 AND weighted_points = 0)),
  CHECK (weighted_points <= weight_points)
);

CREATE TABLE IF NOT EXISTS memos (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  lead_id BIGINT NOT NULL REFERENCES leads(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  compiled_truth_id BIGINT NOT NULL REFERENCES compiled_truth(id) ON DELETE RESTRICT,
  evaluation_id BIGINT NOT NULL REFERENCES evaluations(id) ON DELETE RESTRICT,
  memo_version INTEGER NOT NULL CHECK (memo_version > 0),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'review', 'approved', 'superseded', 'invalid')),
  title TEXT NOT NULL CHECK (btrim(title) <> ''),
  content_uri TEXT NOT NULL CHECK (btrim(content_uri) <> ''),
  content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
  frozen_evidence_hash TEXT NOT NULL CHECK (frozen_evidence_hash ~ '^[0-9a-f]{64}$'),
  citation_coverage_percent NUMERIC(5,2) NOT NULL
    CHECK (citation_coverage_percent >= 0 AND citation_coverage_percent <= 100),
  generated_by TEXT NOT NULL,
  reviewed_by TEXT,
  reviewed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (lead_id, memo_version),
  UNIQUE (content_sha256),
  CHECK (status <> 'approved' OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS memos_one_approved_uidx
  ON memos (lead_id) WHERE status = 'approved';

CREATE TABLE IF NOT EXISTS approvals (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  request_id TEXT NOT NULL CHECK (btrim(request_id) <> ''),
  idempotency_key TEXT NOT NULL CHECK (btrim(idempotency_key) <> ''),
  token_hash TEXT NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
  scope_hash TEXT NOT NULL CHECK (scope_hash ~ '^[0-9a-f]{64}$'),
  scope JSONB NOT NULL CHECK (jsonb_typeof(scope) = 'object'),
  action_preview JSONB NOT NULL CHECK (jsonb_typeof(action_preview) = 'object'),
  action_type TEXT NOT NULL CHECK (btrim(action_type) <> ''),
  target_system TEXT NOT NULL CHECK (btrim(target_system) <> ''),
  target_tenant_id TEXT,
  target_channel_id TEXT,
  lead_id BIGINT REFERENCES leads(id) ON DELETE RESTRICT,
  company_id BIGINT REFERENCES companies(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  payload_hash TEXT NOT NULL CHECK (payload_hash ~ '^[0-9a-f]{64}$'),
  quantitative_limits JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(quantitative_limits) = 'object'),
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'approved', 'rejected', 'revoked', 'expired', 'consumed')),
  requested_by TEXT NOT NULL CHECK (btrim(requested_by) <> ''),
  approver_id TEXT,
  approval_channel_id TEXT,
  decision_note TEXT,
  requested_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  issued_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  governed_transaction_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (request_id),
  UNIQUE (idempotency_key),
  UNIQUE (token_hash),
  CHECK (expires_at > requested_at),
  CHECK (issued_at IS NULL OR expires_at > issued_at),
  CHECK (status NOT IN ('approved', 'consumed') OR (approver_id IS NOT NULL AND approval_channel_id IS NOT NULL AND issued_at IS NOT NULL)),
  CHECK (status <> 'consumed' OR (consumed_at IS NOT NULL AND governed_transaction_id IS NOT NULL)),
  CHECK (consumed_at IS NULL OR consumed_at < expires_at)
);

CREATE INDEX IF NOT EXISTS approvals_pending_expiry_idx
  ON approvals (expires_at) WHERE status IN ('pending', 'approved');
CREATE INDEX IF NOT EXISTS approvals_workflow_idx
  ON approvals (workflow_run_id) WHERE workflow_run_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS notification_outbox (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  idempotency_key TEXT NOT NULL CHECK (btrim(idempotency_key) <> ''),
  dedupe_key TEXT NOT NULL CHECK (btrim(dedupe_key) <> ''),
  provider TEXT NOT NULL CHECK (provider IN ('slack', 'teams', 'internal_log')),
  provider_account_id TEXT NOT NULL CHECK (btrim(provider_account_id) <> ''),
  destination_id TEXT NOT NULL CHECK (btrim(destination_id) <> ''),
  lead_id BIGINT REFERENCES leads(id) ON DELETE RESTRICT,
  company_id BIGINT REFERENCES companies(id) ON DELETE RESTRICT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  approval_id BIGINT REFERENCES approvals(id) ON DELETE RESTRICT,
  severity TEXT NOT NULL
    CHECK (severity IN ('silent_log', 'batched', 'normal', 'urgent')),
  urgent_category TEXT
    CHECK (urgent_category IS NULL OR urgent_category IN (
      'security_incident', 'data_exposure', 'production_blocker',
      'partner_review_blocker', 'approval_expiring'
    )),
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN (
      'draft', 'queued', 'held', 'dispatching', 'retry',
      'sent', 'failed', 'cancelled', 'logged'
    )),
  subject TEXT NOT NULL CHECK (btrim(subject) <> ''),
  body_hash TEXT NOT NULL CHECK (body_hash ~ '^[0-9a-f]{64}$'),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(payload) = 'object'),
  timezone TEXT NOT NULL DEFAULT 'Europe/Berlin',
  policy_version TEXT NOT NULL,
  deliver_after TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  max_attempts INTEGER NOT NULL DEFAULT 5 CHECK (max_attempts BETWEEN 1 AND 20),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  claim_id TEXT,
  claimed_by TEXT,
  claimed_at TIMESTAMPTZ,
  lease_expires_at TIMESTAMPTZ,
  next_attempt_at TIMESTAMPTZ,
  last_error_class TEXT,
  last_error_message TEXT,
  provider_message_id TEXT,
  sent_at TIMESTAMPTZ,
  cancelled_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (idempotency_key),
  UNIQUE (provider, provider_account_id, dedupe_key),
  CHECK (severity <> 'urgent' OR urgent_category IS NOT NULL),
  CHECK (severity <> 'silent_log' OR provider = 'internal_log'),
  CHECK (attempt_count <= max_attempts),
  CHECK (status <> 'dispatching' OR (claim_id IS NOT NULL AND claimed_by IS NOT NULL AND lease_expires_at IS NOT NULL)),
  CHECK (status <> 'sent' OR (provider_message_id IS NOT NULL AND sent_at IS NOT NULL)),
  CHECK (status <> 'cancelled' OR cancelled_at IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS notification_outbox_dispatch_idx
  ON notification_outbox (COALESCE(next_attempt_at, deliver_after), id)
  WHERE status IN ('queued', 'retry');
CREATE INDEX IF NOT EXISTS notification_outbox_held_idx
  ON notification_outbox (deliver_after, id) WHERE status = 'held';
CREATE UNIQUE INDEX IF NOT EXISTS notification_provider_message_uidx
  ON notification_outbox (provider, provider_account_id, provider_message_id)
  WHERE provider_message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS notification_attempts (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  outbox_id BIGINT NOT NULL REFERENCES notification_outbox(id) ON DELETE RESTRICT,
  attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
  claim_id TEXT NOT NULL CHECK (btrim(claim_id) <> ''),
  status TEXT NOT NULL
    CHECK (status IN ('started', 'succeeded', 'retryable_failure', 'permanent_failure', 'abandoned')),
  provider_request_id TEXT,
  provider_response_code TEXT,
  provider_message_id TEXT,
  error_class TEXT,
  error_message TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  finished_at TIMESTAMPTZ,
  response_metadata JSONB NOT NULL DEFAULT '{}'::jsonb
    CHECK (jsonb_typeof(response_metadata) = 'object'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (outbox_id, attempt_number),
  UNIQUE (outbox_id, claim_id),
  CHECK (status = 'started' OR finished_at IS NOT NULL),
  CHECK (status <> 'succeeded' OR provider_message_id IS NOT NULL),
  CHECK (status NOT IN ('retryable_failure', 'permanent_failure') OR error_class IS NOT NULL)
);

CREATE INDEX IF NOT EXISTS notification_attempt_provider_request_idx
  ON notification_attempts (provider_request_id)
  WHERE provider_request_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS audit_events (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (btrim(event_type) <> ''),
  actor_id TEXT NOT NULL CHECK (btrim(actor_id) <> ''),
  actor_type TEXT NOT NULL DEFAULT 'service'
    CHECK (actor_type IN ('operator', 'service', 'agent', 'system')),
  transaction_id TEXT,
  request_id TEXT,
  workflow_run_id BIGINT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
  entity_table TEXT NOT NULL CHECK (btrim(entity_table) <> ''),
  entity_id TEXT NOT NULL CHECK (btrim(entity_id) <> ''),
  before_state JSONB,
  after_state JSONB,
  details JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details) = 'object'),
  occurred_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS audit_events_entity_idx
  ON audit_events (entity_table, entity_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_workflow_idx
  ON audit_events (workflow_run_id, occurred_at DESC)
  WHERE workflow_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS audit_events_transaction_idx
  ON audit_events (transaction_id) WHERE transaction_id IS NOT NULL;

-- Generic update timestamps/version counters.
DO $block$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'sources', 'evidence_artifacts', 'document_extractions', 'contradictions',
    'memos', 'approvals', 'notification_outbox'
  ]
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_trigger
      WHERE tgrelid = to_regclass(table_name) AND tgname = table_name || '_set_updated_at'
    ) THEN
      EXECUTE format(
        'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
        table_name || '_set_updated_at', table_name
      );
    END IF;
  END LOOP;

  FOREACH table_name IN ARRAY ARRAY['companies', 'leads']
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_trigger
      WHERE tgrelid = to_regclass(table_name) AND tgname = table_name || '_touch_version'
    ) THEN
      EXECUTE format(
        'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION touch_versioned_row()',
        table_name || '_touch_version', table_name
      );
    END IF;
  END LOOP;
END;
$block$;

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

CREATE OR REPLACE FUNCTION guard_initial_workflow_run()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
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
$function$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid = 'workflow_runs'::regclass AND tgname = 'workflow_runs_guard_transition'
  ) THEN
    CREATE TRIGGER workflow_runs_guard_transition
      BEFORE UPDATE ON workflow_runs
      FOR EACH ROW EXECUTE FUNCTION guard_workflow_run_transition();
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid = 'workflow_runs'::regclass AND tgname = 'workflow_runs_guard_initial'
  ) THEN
    CREATE TRIGGER workflow_runs_guard_initial
      BEFORE INSERT ON workflow_runs
      FOR EACH ROW EXECUTE FUNCTION guard_initial_workflow_run();
  END IF;
END;
$block$;

CREATE OR REPLACE FUNCTION guard_approval_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
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
$function$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid = 'approvals'::regclass AND tgname = 'approvals_guard_transition'
  ) THEN
    CREATE TRIGGER approvals_guard_transition
      BEFORE INSERT OR UPDATE ON approvals
      FOR EACH ROW EXECUTE FUNCTION guard_approval_transition();
  END IF;
END;
$block$;

CREATE OR REPLACE FUNCTION guard_initial_notification()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
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
$function$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid = 'notification_outbox'::regclass AND tgname = 'notification_outbox_guard_initial'
  ) THEN
    CREATE TRIGGER notification_outbox_guard_initial
      BEFORE INSERT ON notification_outbox
      FOR EACH ROW EXECUTE FUNCTION guard_initial_notification();
  END IF;
END;
$block$;

CREATE OR REPLACE FUNCTION guard_compiled_truth_fact()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
DECLARE
  stored_status TEXT;
BEGIN
  SELECT fact_status INTO stored_status FROM facts WHERE id = NEW.fact_id;
  IF NEW.support_role = 'current' AND stored_status <> 'verified_fact' THEN
    RAISE EXCEPTION 'current compiled truth requires verified facts (fact_id=%)', NEW.fact_id
      USING ERRCODE = '23514';
  END IF;
  IF NEW.support_role = 'current' AND NOT EXISTS (
    SELECT 1 FROM fact_sources WHERE fact_id = NEW.fact_id
  ) THEN
    RAISE EXCEPTION 'current compiled truth requires resolvable fact provenance (fact_id=%)', NEW.fact_id
      USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END;
$function$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid = 'compiled_truth_facts'::regclass AND tgname = 'compiled_truth_facts_guard'
  ) THEN
    CREATE TRIGGER compiled_truth_facts_guard
      BEFORE INSERT OR UPDATE ON compiled_truth_facts
      FOR EACH ROW EXECUTE FUNCTION guard_compiled_truth_fact();
  END IF;
END;
$block$;

CREATE OR REPLACE FUNCTION prevent_audit_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
BEGIN
  RAISE EXCEPTION 'audit_events is append-only' USING ERRCODE = '55000';
END;
$function$;

CREATE OR REPLACE FUNCTION prevent_migration_record_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $function$
BEGIN
  RAISE EXCEPTION 'schema_migrations is append-only; checksum mismatches fail closed'
    USING ERRCODE = '55000';
END;
$function$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid = 'audit_events'::regclass AND tgname = 'audit_events_append_only'
  ) THEN
    CREATE TRIGGER audit_events_append_only
      BEFORE UPDATE OR DELETE OR TRUNCATE ON audit_events
      FOR EACH STATEMENT EXECUTE FUNCTION prevent_audit_mutation();
  END IF;
END;
$block$;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger
    WHERE tgrelid = 'schema_migrations'::regclass AND tgname = 'schema_migrations_append_only'
  ) THEN
    CREATE TRIGGER schema_migrations_append_only
      BEFORE UPDATE OR DELETE OR TRUNCATE ON schema_migrations
      FOR EACH STATEMENT EXECUTE FUNCTION prevent_migration_record_mutation();
  END IF;
END;
$block$;

-- Atomic optimistic workflow transition. Cancellation is sticky through the trigger.
CREATE OR REPLACE FUNCTION transition_workflow_run(
  p_run_id TEXT,
  p_expected_record_version BIGINT,
  p_new_status TEXT,
  p_flow_revision BIGINT DEFAULT NULL,
  p_actor_id TEXT DEFAULT 'vcops',
  p_result JSONB DEFAULT NULL,
  p_error_class TEXT DEFAULT NULL,
  p_error_message TEXT DEFAULT NULL
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
$function$;

-- Requests cooperative cancellation without pretending the run is terminal.
CREATE OR REPLACE FUNCTION request_workflow_cancel(
  p_run_id TEXT,
  p_expected_record_version BIGINT,
  p_actor_id TEXT,
  p_reason TEXT
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
$function$;

-- Records a stable human decision without exposing raw table updates.
CREATE OR REPLACE FUNCTION decide_approval(
  p_request_id TEXT,
  p_decision TEXT,
  p_approver_id TEXT,
  p_approval_channel_id TEXT,
  p_note TEXT,
  p_actor_id TEXT
)
RETURNS SETOF approvals
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
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
$function$;

-- One-time approval consumption. Call in the same transaction as the governed write.
CREATE OR REPLACE FUNCTION consume_approval(
  p_token_hash TEXT,
  p_scope_hash TEXT,
  p_action_type TEXT,
  p_target_system TEXT,
  p_payload_hash TEXT,
  p_governed_transaction_id TEXT,
  p_actor_id TEXT
)
RETURNS SETOF approvals
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
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
$function$;

-- Atomically claims one due notification. Provider I/O occurs after commit.
CREATE OR REPLACE FUNCTION claim_notification(
  p_worker_id TEXT,
  p_lease_seconds INTEGER DEFAULT 60
)
RETURNS SETOF notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION finish_notification_attempt(
  p_outbox_id BIGINT,
  p_claim_id TEXT,
  p_outcome TEXT,
  p_provider_request_id TEXT DEFAULT NULL,
  p_provider_response_code TEXT DEFAULT NULL,
  p_provider_message_id TEXT DEFAULT NULL,
  p_error_class TEXT DEFAULT NULL,
  p_error_message TEXT DEFAULT NULL,
  p_retry_after_seconds INTEGER DEFAULT NULL
)
RETURNS SETOF notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION release_held_notification(
  p_outbox_id BIGINT,
  p_actor_id TEXT
)
RETURNS SETOF notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
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
$function$;

CREATE OR REPLACE FUNCTION cancel_notification(
  p_outbox_id BIGINT,
  p_actor_id TEXT
)
RETURNS SETOF notification_outbox
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
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
$function$;

COMMIT;
