-- SPDX-License-Identifier: Apache-2.0
-- Venture Capital Lead Research System 3.0
-- Typed company identity and append-only entity-resolution evidence.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

CREATE TABLE IF NOT EXISTS company_aliases (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  alias_kind TEXT NOT NULL DEFAULT 'trade_name'
    CHECK (alias_kind IN ('canonical_name', 'legal_name', 'trade_name', 'former_name', 'acronym', 'other')),
  alias_value TEXT NOT NULL CHECK (btrim(alias_value) <> ''),
  normalized_alias TEXT NOT NULL CHECK (btrim(normalized_alias) = normalized_alias AND normalized_alias <> ''),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'deprecated', 'disputed')),
  confidentiality TEXT NOT NULL DEFAULT 'internal'
    CHECK (confidentiality IN ('public', 'internal', 'confidential', 'restricted')),
  confidence NUMERIC(4,3) NOT NULL DEFAULT 1.000 CHECK (confidence >= 0 AND confidence <= 1),
  source_id BIGINT REFERENCES sources(id) ON DELETE RESTRICT,
  valid_from DATE,
  valid_to DATE,
  created_by TEXT NOT NULL DEFAULT 'migration-006' CHECK (btrim(created_by) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE UNIQUE INDEX IF NOT EXISTS company_aliases_active_company_uidx
  ON company_aliases (company_id, normalized_alias, alias_kind)
  WHERE status = 'active' AND valid_to IS NULL;
CREATE INDEX IF NOT EXISTS company_aliases_exact_idx
  ON company_aliases (normalized_alias, confidentiality)
  WHERE status = 'active' AND valid_to IS NULL;
CREATE INDEX IF NOT EXISTS company_aliases_fuzzy_bucket_idx
  ON company_aliases (lower(left(normalized_alias, 1)), length(normalized_alias))
  WHERE status = 'active' AND valid_to IS NULL;
CREATE INDEX IF NOT EXISTS company_aliases_length_idx
  ON company_aliases (length(normalized_alias))
  WHERE status = 'active' AND valid_to IS NULL;

CREATE INDEX IF NOT EXISTS companies_name_length_idx
  ON companies (length(lower(name)));

CREATE TABLE IF NOT EXISTS company_domains (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  hostname TEXT NOT NULL CHECK (
    hostname = lower(btrim(hostname)) AND hostname <> '' AND hostname !~ '[/@:]'
  ),
  domain_kind TEXT NOT NULL DEFAULT 'primary'
    CHECK (domain_kind IN ('primary', 'redirect', 'former', 'product', 'other')),
  status TEXT NOT NULL DEFAULT 'claimed'
    CHECK (status IN ('verified', 'claimed', 'deprecated', 'disputed')),
  confidentiality TEXT NOT NULL DEFAULT 'internal'
    CHECK (confidentiality IN ('public', 'internal', 'confidential', 'restricted')),
  confidence NUMERIC(4,3) NOT NULL DEFAULT 1.000 CHECK (confidence >= 0 AND confidence <= 1),
  source_id BIGINT REFERENCES sources(id) ON DELETE RESTRICT,
  verified_at TIMESTAMPTZ,
  valid_from DATE,
  valid_to DATE,
  created_by TEXT NOT NULL DEFAULT 'migration-006' CHECK (btrim(created_by) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from),
  CHECK (status <> 'verified' OR verified_at IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS company_domains_active_hostname_uidx
  ON company_domains (hostname)
  WHERE status IN ('verified', 'claimed') AND valid_to IS NULL;
CREATE INDEX IF NOT EXISTS company_domains_company_idx
  ON company_domains (company_id, status, valid_to);

CREATE TABLE IF NOT EXISTS company_external_ids (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  provider TEXT NOT NULL CHECK (provider = lower(btrim(provider)) AND provider <> ''),
  provider_account_id TEXT NOT NULL DEFAULT 'default' CHECK (btrim(provider_account_id) <> ''),
  external_id TEXT NOT NULL CHECK (btrim(external_id) <> ''),
  status TEXT NOT NULL DEFAULT 'verified'
    CHECK (status IN ('verified', 'claimed', 'deprecated', 'disputed')),
  confidentiality TEXT NOT NULL DEFAULT 'internal'
    CHECK (confidentiality IN ('public', 'internal', 'confidential', 'restricted')),
  confidence NUMERIC(4,3) NOT NULL DEFAULT 1.000 CHECK (confidence >= 0 AND confidence <= 1),
  source_id BIGINT REFERENCES sources(id) ON DELETE RESTRICT,
  valid_from DATE,
  valid_to DATE,
  created_by TEXT NOT NULL DEFAULT 'vcops' CHECK (btrim(created_by) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to >= valid_from)
);

CREATE UNIQUE INDEX IF NOT EXISTS company_external_ids_active_uidx
  ON company_external_ids (provider, provider_account_id, external_id)
  WHERE status IN ('verified', 'claimed') AND valid_to IS NULL;
CREATE INDEX IF NOT EXISTS company_external_ids_company_idx
  ON company_external_ids (company_id, status, valid_to);

CREATE TABLE IF NOT EXISTS entity_resolution_runs (
  id UUID PRIMARY KEY,
  workflow_request_id BIGINT REFERENCES workflow_requests(id) ON DELETE RESTRICT,
  requester_id TEXT NOT NULL CHECK (btrim(requester_id) <> ''),
  purpose TEXT NOT NULL CHECK (purpose IN (
    'company_creation', 'research', 'qualification', 'memo', 'merge_review', 'compatibility_lookup'
  )),
  max_confidentiality TEXT NOT NULL
    CHECK (max_confidentiality IN ('public', 'internal', 'confidential', 'restricted')),
  idempotency_key TEXT NOT NULL CHECK (btrim(idempotency_key) <> ''),
  query_hash TEXT NOT NULL CHECK (query_hash ~ '^[0-9a-f]{64}$'),
  identity_query JSONB NOT NULL CHECK (jsonb_typeof(identity_query) = 'object'),
  policy_version TEXT NOT NULL DEFAULT 'entity-resolution.v1' CHECK (btrim(policy_version) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE UNIQUE INDEX IF NOT EXISTS entity_resolution_runs_request_uidx
  ON entity_resolution_runs (requester_id, purpose, idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS entity_resolution_runs_workflow_request_uidx
  ON entity_resolution_runs (workflow_request_id)
  WHERE workflow_request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS entity_resolution_runs_query_hash_idx
  ON entity_resolution_runs (query_hash, created_at DESC);

CREATE TABLE IF NOT EXISTS entity_resolution_decisions (
  id UUID PRIMARY KEY,
  resolution_run_id UUID NOT NULL UNIQUE REFERENCES entity_resolution_runs(id) ON DELETE RESTRICT,
  outcome TEXT NOT NULL
    CHECK (outcome IN ('existing', 'new_allowed', 'human_review', 'no_match', 'denied')),
  matched_company_id BIGINT REFERENCES companies(id) ON DELETE RESTRICT,
  match_method TEXT,
  match_confidence NUMERIC(4,3) CHECK (match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)),
  candidate_company_ids JSONB NOT NULL DEFAULT '[]'::jsonb
    CHECK (jsonb_typeof(candidate_company_ids) = 'array'),
  reasons JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(reasons) = 'array'),
  policy_version TEXT NOT NULL DEFAULT 'entity-resolution.v1' CHECK (btrim(policy_version) <> ''),
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (
    (outcome = 'existing' AND matched_company_id IS NOT NULL) OR
    (outcome <> 'existing' AND matched_company_id IS NULL)
  )
);

CREATE INDEX IF NOT EXISTS entity_resolution_decisions_company_idx
  ON entity_resolution_decisions (matched_company_id, created_at DESC)
  WHERE matched_company_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS entity_resolution_decisions_outcome_idx
  ON entity_resolution_decisions (outcome, created_at DESC);

CREATE TABLE IF NOT EXISTS entity_resolution_consumptions (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  resolution_decision_id UUID NOT NULL UNIQUE REFERENCES entity_resolution_decisions(id) ON DELETE RESTRICT,
  company_id BIGINT NOT NULL REFERENCES companies(id) ON DELETE RESTRICT,
  outcome TEXT NOT NULL CHECK (outcome IN ('linked_existing', 'created_new')),
  consumed_by TEXT NOT NULL CHECK (btrim(consumed_by) <> ''),
  consumed_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE INDEX IF NOT EXISTS entity_resolution_consumptions_company_idx
  ON entity_resolution_consumptions (company_id, consumed_at DESC);

-- Existing canonical rows become resolver evidence without changing their
-- historical company records. They are internal until explicitly reclassified.
-- normalize() runs BEFORE btrim(), not after. btrim() with no character
-- argument strips only U+0020, while NFKC maps U+00A0 NO-BREAK SPACE and U+3000
-- IDEOGRAPHIC SPACE (among others) onto U+0020 -- so trimming first let
-- normalization reintroduce edge whitespace and the derived value then failed
-- this table's own CHECK (btrim(normalized_alias) = normalized_alias). Measured
-- on PostgreSQL 17.10: name 'Acme ' produced 'acme ' and aborted the
-- migration, which under migrate.sh's ON_ERROR_STOP takes the whole upgrade with
-- it. companies.name is TEXT NOT NULL with no trim constraint, so such a name is
-- storable and a name pasted from a PDF or web page plausibly carries one.
INSERT INTO company_aliases
  (company_id, alias_kind, alias_value, normalized_alias, status, confidentiality, confidence)
SELECT id, 'canonical_name', name, lower(btrim(normalize(name, NFKC))), 'active', 'internal', 1.000
FROM companies
WHERE btrim(normalize(name, NFKC)) <> ''
ON CONFLICT DO NOTHING;

INSERT INTO company_domains
  (company_id, hostname, domain_kind, status, confidentiality, confidence, verified_at)
SELECT id, canonical_domain, 'primary', 'verified', 'internal', 1.000, updated_at
FROM companies
WHERE canonical_domain IS NOT NULL
ON CONFLICT DO NOTHING;

DO $block$
DECLARE
  table_name TEXT;
BEGIN
  FOREACH table_name IN ARRAY ARRAY[
    'entity_resolution_runs', 'entity_resolution_decisions', 'entity_resolution_consumptions'
  ]
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM pg_trigger
      WHERE tgrelid=to_regclass(table_name) AND tgname=table_name || '_append_only'
    ) THEN
      EXECUTE format(
        'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %I FOR EACH ROW EXECUTE FUNCTION prevent_domain_history_mutation()',
        table_name || '_append_only', table_name
      );
    END IF;
  END LOOP;
END;
$block$;

REVOKE ALL ON company_aliases, company_domains, company_external_ids,
  entity_resolution_runs, entity_resolution_decisions, entity_resolution_consumptions
FROM openclaw_runtime;

GRANT SELECT, INSERT ON company_aliases, company_domains, company_external_ids,
  entity_resolution_runs, entity_resolution_decisions, entity_resolution_consumptions
TO openclaw_runtime;

GRANT USAGE, SELECT ON SEQUENCE company_aliases_id_seq,
  company_domains_id_seq, company_external_ids_id_seq,
  entity_resolution_consumptions_id_seq
TO openclaw_runtime;

COMMIT;
