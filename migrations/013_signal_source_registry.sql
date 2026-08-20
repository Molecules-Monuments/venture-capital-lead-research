-- SPDX-License-Identifier: Apache-2.0
-- Venture Capital Lead Research System 3.0
-- Restore automated source surveillance: a queryable watchlist registry that a
-- scheduled or operator-triggered source-scan can read by cadence. The
-- primary_sources.md watchlist was documentation-only; this makes it data.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

CREATE TABLE IF NOT EXISTS signal_sources (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_name TEXT NOT NULL CHECK (btrim(source_name) <> ''),
  canonical_uri TEXT NOT NULL,
  source_class TEXT NOT NULL CHECK (source_class IN (
    'company_blog', 'vc_portfolio', 'news_rss', 'press_release',
    'research_report', 'open_source', 'job_board', 'other'
  )),
  cadence TEXT NOT NULL CHECK (cadence IN ('daily', 'weekly', 'monthly')),
  thesis_relevance TEXT,
  expected_signal TEXT,
  rate_constraint TEXT,
  owner TEXT NOT NULL CHECK (btrim(owner) <> ''),
  confidentiality TEXT NOT NULL DEFAULT 'internal'
    CHECK (confidentiality IN ('public', 'internal', 'confidential', 'restricted')),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  last_scanned_at TIMESTAMPTZ,
  -- 'claimed' is the honest claim-time state: source-scan bumps last_scanned_at
  -- and marks the source claimed for this cadence cycle before any screening has
  -- run, so it must not assert 'succeeded'. The outcome states (succeeded/
  -- no_new_signals/failed) are for a future completion callback; today a claimed
  -- cycle stays 'claimed'.
  last_scan_status TEXT
    CHECK (last_scan_status IS NULL OR last_scan_status IN ('claimed', 'succeeded', 'no_new_signals', 'failed')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
  row_version BIGINT NOT NULL DEFAULT 1 CHECK (row_version > 0),
  created_by TEXT NOT NULL CHECK (btrim(created_by) <> ''),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (canonical_uri)
);

-- Same normalization rule as sources.canonical_uri (012): trimmed, lowercase
-- scheme and authority, path and query case preserved because they are
-- meaningful. The earlier inline rule lowercased the WHOLE URI, which rejected
-- every legitimate watchlist URL carrying an uppercase path segment — the
-- helper feeds this column normalize_uri() output, which preserves path case,
-- so `source-watch https://news.example/Feed` failed at the constraint.
-- Stated as a named constraint (not inline) so re-running this migration
-- against a database created by the earlier rule converges on the new one.
ALTER TABLE signal_sources DROP CONSTRAINT IF EXISTS signal_sources_canonical_uri_check;
DO $block$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'signal_sources_canonical_uri_normalized_check'
  ) THEN
    ALTER TABLE signal_sources ADD CONSTRAINT signal_sources_canonical_uri_normalized_check
      CHECK (
        canonical_uri = btrim(canonical_uri)
        AND canonical_uri ~ '^https?://'
        AND substring(canonical_uri from '^https?://[^/?#]*') =
            lower(substring(canonical_uri from '^https?://[^/?#]*'))
      );
  END IF;
END;
$block$;

CREATE INDEX IF NOT EXISTS signal_sources_due_idx
  ON signal_sources (cadence, last_scanned_at) WHERE enabled;

-- A source is due when it has never been scanned or its cadence interval has
-- elapsed. Evaluated in SQL so the scan lane cannot assert a source is due.
-- STABLE, not IMMUTABLE: the due test reads the transaction clock via now(), so
-- its result is not a pure function of its arguments. now() (transaction start)
-- is deterministic within the evaluating statement, which is exactly what a
-- cadence check needs. An out-of-enum cadence raises rather than silently
-- evaluating to NULL (which a WHERE clause would read as "not due" and quietly
-- skip the source); the signal_sources.cadence CHECK keeps stored rows in range,
-- and this makes a direct mis-call fail loud.
CREATE OR REPLACE FUNCTION signal_source_is_due(
  p_cadence TEXT,
  p_last_scanned_at TIMESTAMPTZ
)
RETURNS BOOLEAN
LANGUAGE plpgsql
STABLE
SET search_path = pg_catalog, public
AS $function$
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
$function$;

DROP TRIGGER IF EXISTS signal_sources_touch_version ON signal_sources;
CREATE TRIGGER signal_sources_touch_version
  BEFORE UPDATE ON signal_sources
  FOR EACH ROW EXECUTE FUNCTION touch_versioned_row();

-- The registry is operator-curated and scan-updated: the runtime role reads it,
-- inserts a watched source, and updates enable/cadence/last_scanned_at. It is
-- not append-only (a watchlist is edited in place) and carries no lead/company
-- lineage, so no fixed-workflow scope constraint applies.
REVOKE ALL ON signal_sources FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE ON signal_sources TO openclaw_runtime;
GRANT USAGE, SELECT ON SEQUENCE signal_sources_id_seq TO openclaw_runtime;
REVOKE ALL ON FUNCTION signal_source_is_due(TEXT, TIMESTAMPTZ) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION signal_source_is_due(TEXT, TIMESTAMPTZ) TO openclaw_runtime;

COMMIT;
