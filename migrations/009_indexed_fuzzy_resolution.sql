-- OpenClaw Lead Research System 3.0
-- Indexed, review-only fuzzy entity-resolution candidates.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '120s';

CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;

CREATE INDEX IF NOT EXISTS companies_name_trgm_idx
  ON companies USING gin (lower(name) gin_trgm_ops);

CREATE INDEX IF NOT EXISTS company_aliases_normalized_trgm_idx
  ON company_aliases USING gin (normalized_alias gin_trgm_ops)
  WHERE status = 'active' AND valid_to IS NULL;

-- Migration 002 revokes the default PUBLIC execute privilege on all functions.
-- Grant only the two immutable functions required by the reviewed resolver
-- query; runtime receives no extension-management or inspection functions.
REVOKE ALL ON FUNCTION public.similarity(TEXT, TEXT) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.similarity_op(TEXT, TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.similarity(TEXT, TEXT) TO openclaw_runtime;
GRANT EXECUTE ON FUNCTION public.similarity_op(TEXT, TEXT) TO openclaw_runtime;

COMMIT;
