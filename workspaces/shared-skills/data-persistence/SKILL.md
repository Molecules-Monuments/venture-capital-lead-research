---
name: data-persistence
description: Validate and submit deterministic Postgres operations through vcops with idempotency, provenance, and transaction boundaries.
---

# Data Persistence

## Inputs

- Typed operation request, actor/run IDs, idempotency key, expected record version, provenance, and supplied persistence policy.
- Optional approval ID for a governed operation.

## Contract

Only `data-steward` executes this skill; `vc-chief` holds it read-only as the
request-authoring contract when constructing persistence requests for the
steward. Postgres is authoritative for lead, evidence, approval, notification,
and workflow business state. Agent-mode `vcops` is read-only: mutations are
limited to the eighteen parameterized fixed `vcrun` workflows with
transactions, foreign-key-safe ordering, and optimistic version checks.
Anything outside those workflows is an operator request through a
non-allowlisted helper, never free-form model-generated SQL.

## Routing a specialist `persistence_request`

Map the packet's `operation` to a lane before doing anything else:

| `operation` | Lane |
|---|---|
| `record_evidence` (founder/traction/market researchers) | fixed workflow `evidence-record`, one invocation per claim |
| `record_intake` | already persisted by the intake fixed workflow that produced the packet; do not re-persist |
| `capture_candidates` | **not a steward lane, and not yet persisted.** A discovered candidate becomes a lead only when the chief invokes the fixed `outbound-scout` workflow **once per candidate** (that workflow takes one `company_name`/`company_domain`/`lead_title` and creates one lead). Refuse the request, and say the candidates are *awaiting* the chief's per-candidate `outbound-scout` invocation — never report them as already persisted, which would strand every candidate in the packet |
| `record_route`, `record_source_outcomes` | no fixed workflow exists in 3.0 — classify `operator_only` and refuse, naming the operation |
| anything else | classify `operator_only` and refuse |

For `orchestration-record` with `record_kind=chief_output`, pass the literal
`specialist` value `vc-chief` (the selector requires a non-empty string; the
handler stores it for the chief's terminal record).

## The `evidence_json` payload contract (evidence-record)

`vcrun run evidence-record` takes `evidence_json`: ONE claim as one JSON
object. Unknown fields are refused. Fields:

- Required: `claim` (the statement, ≤2000 chars), `fact_type` (the metric or
  decision question the claim answers, e.g. `arr_run_rate`,
  `founder_prior_exit`, ≤200), `produced_by` (the producing specialist role
  id, e.g. `founder-researcher`).
- `confidence`: 0..1 number, or `low`/`medium`/`high` (accepted and mapped to
  0.3/0.6/0.9). `evaluate-lead` compiles its truth snapshot from facts at
  **0.7 or above**, so a fact recorded as `medium` (0.6) is stored and
  retrievable but does not by itself let a lead reach an evaluation. Record
  `high` only where the evidence genuinely supports it, and expect a lead whose
  facts are all `medium` or below to stop at compiled truth.
- Exactly one of `source` (web provenance) or `document` (extraction
  provenance):
  - `source`: `{url, kind, trust_level, title, published_at, accessed_at,
    content_sha256}`. `kind` ∈ `public_web | company_website | paid_connector |
    regulatory_filing`. `trust_level` ∈ `public_web | paid_connector` (the
    only trust levels a model lane may assert; everything else is refused).
    `content_sha256` (optional, 64 lowercase hex) is the hash of the fetched
    page bytes. Web claims corroborate toward `verified_fact` **only by distinct
    verified content hash**, not by host: supply the sha256 of what `web_fetch`
    returned so two genuinely-independent pages count as two, while a bare URL
    (no `content_sha256`) or two URLs with identical content never corroborate.
    A claim recorded without content hashes stays a `submitted_claim` for the
    human evaluate-lead gate — which is the safe default.
  - `document`: `{extraction_id, page_number, sheet_name, cell_range,
    paragraph_number, locator}` — `extraction_id` of a succeeded extraction
    plus at least one locator. An artifact associated with specific leads may
    only be cited for one of those leads (citing another lead's document is
    refused); lead-free manual ingests remain citable.
- Optional: `value` (defaults to the claim text), `value_kind`
  (`text`/`numeric`), `unit`, `currency` (3-letter), `period_start`,
  `period_end`, `cohort`, `measurement_basis`, `observed_at`, `source_date`,
  `citation`, `locator`.

Mapping a researcher packet evidence item: `claim`→`claim`;
`source_url`→`source.url`; `retrieved_at`→`source.accessed_at`;
`published_or_observed_at`→`source.published_at`; `publisher`→`source.title`;
`confidence`→`confidence`; set `produced_by` to the specialist role and derive
`fact_type` from the decision question the claim answers. `source_class` maps
to `source.kind`: `primary_company`→`company_website`,
`court_or_regulatory`→`regulatory_filing`, everything else→`public_web`
(`paid_connector` only when the evidence came through a paid connector).
Set `source.content_sha256` to the sha256 of the fetched page bytes when the
specialist retrieved the page through `web_fetch`; omit it when the page was
not fetched-and-hashed. Drop `evidence_id`, `person_id`, `fact_status`, and
`direct_source_inspected` — they do not exist on this lane, and every recorded
fact lands as `submitted_claim` regardless of the packet's asserted status;
promotion to `verified_fact` happens only through the deterministic
corroboration gate (`fact-promote`), which counts web sources by distinct
verified content hash.

## Evidence and failures

Return machine-readable validation and affected IDs/versions. On conflict, constraint failure, unavailable database, replay, or partial-operation risk, roll back and return a retry-safe error. Never claim success without committed transaction evidence.

## Output

Return exactly one object valid against [`../../schemas/data-steward-output.schema.json`](../../schemas/data-steward-output.schema.json). The schema is the sole authority for field names, enums, required values, and nullability; do not maintain a parallel output definition here. It rejects unknown fields, so the persistence facts belong in the `result` object it already defines — `operation`, `availability`, `mode`, `pre_state`, `post_state`, `record_ids`, `revision`, `idempotency_key`, `rows_affected`, `preview`, `approval_required`, and `verification`. No external SaaS write or channel send.
