-- OpenClaw Lead Research System 3.0
-- Autonomous research-intelligence persistence: claim identity, the reviewed
-- promotion policy, and the deterministic claim-to-verified-fact promotion
-- boundary (SECURITY DEFINER; a caller cannot assert its way past it).

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

-- Deterministic content identity for submitted claims so a second independent
-- source attaches to the same claim row instead of duplicating it.
ALTER TABLE facts
  ADD COLUMN IF NOT EXISTS claim_hash TEXT;

DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'facts_claim_hash_check'
  ) THEN
    ALTER TABLE facts ADD CONSTRAINT facts_claim_hash_check
      CHECK (claim_hash IS NULL OR claim_hash ~ '^[0-9a-f]{64}$');
  END IF;
END;
$block$;

CREATE INDEX IF NOT EXISTS facts_claim_hash_idx
  ON facts (company_id, claim_hash) WHERE claim_hash IS NOT NULL;

-- The promotion-strictness knob as reviewed data, not code. Owner-lane only;
-- the runtime role can read it but never change it. Sources whose trust level
-- is excluded never count toward corroboration, so untrusted uploads (the
-- prompt-injection carrier) cannot corroborate each other into verified facts.
CREATE TABLE IF NOT EXISTS fact_promotion_policy (
  id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
  auto_promote BOOLEAN NOT NULL DEFAULT TRUE,
  min_independent_sources INTEGER NOT NULL DEFAULT 2
    CHECK (min_independent_sources >= 1),
  single_source_kinds TEXT[] NOT NULL DEFAULT ARRAY['regulatory_filing']
    CHECK (single_source_kinds <@ ARRAY[
      'primary_document', 'company_website', 'regulatory_filing', 'channel_message',
      'public_web', 'paid_connector', 'operator_statement', 'internal_analysis',
      'provider_event', 'other'
    ]),
  excluded_trust_levels TEXT[] NOT NULL DEFAULT ARRAY['untrusted_upload', 'unknown']
    CHECK (excluded_trust_levels <@ ARRAY[
      'internal_admin', 'allowlisted_operator', 'remote_channel', 'public_web',
      'paid_connector', 'untrusted_upload', 'generated_internal', 'unknown'
    ]),
  -- Hosts whose pages the evidence lane may record as an official/registry
  -- kind. Empty by default: a model label alone must never make a source
  -- qualify for single-source promotion.
  official_source_domains TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  updated_by TEXT NOT NULL DEFAULT 'migration-012' CHECK (btrim(updated_by) <> ''),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO fact_promotion_policy (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

-- Promotion is supersession, never mutation: facts stay append-only. The
-- corroboration predicate is evaluated here, in SQL, against the reviewed
-- policy row; the caller contributes nothing but the fact id and its identity.
-- Registrable-host extraction for source-independence counting. This is a
-- deliberate, reviewed approximation of the public-suffix list: the last two
-- labels, or the last three when the ending is a well-known two-part public
-- suffix (co.uk, com.au, ...). Unknown multi-part suffixes therefore collapse
-- toward FEWER independent sources, never more — the conservative direction
-- for corroboration. IPv4 literals also over-collapse (last two octets),
-- which is likewise conservative. Full PSL/content-addressed closure remains
-- the CR-001 part-6 deferral.
CREATE OR REPLACE FUNCTION registrable_host(p_host TEXT)
RETURNS TEXT
LANGUAGE plpgsql
IMMUTABLE
SET search_path = pg_catalog, public
AS $function$
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
$function$;

-- The promotion predicate runs as definer, but the runtime role may also use
-- the pure helper directly (e.g. read-side source grouping and the G4 gate's
-- boundary tests); this database revokes default function EXECUTE.
REVOKE ALL ON FUNCTION registrable_host(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION registrable_host(TEXT) TO openclaw_runtime;

CREATE OR REPLACE FUNCTION promote_submitted_claim(
  p_fact_id BIGINT,
  p_actor TEXT DEFAULT 'vcops'
)
RETURNS SETOF facts
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $function$
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
$function$;

REVOKE ALL ON fact_promotion_policy FROM PUBLIC;
GRANT SELECT ON fact_promotion_policy TO openclaw_runtime;
REVOKE ALL ON FUNCTION promote_submitted_claim(BIGINT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION promote_submitted_claim(BIGINT, TEXT) TO openclaw_runtime;

COMMIT;
