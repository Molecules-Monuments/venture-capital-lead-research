# Agent Research: Data Steward

Access date for web sources: 2026-07-20. Implementation decision: **adopt a
narrower executor contract; test identity-resolution additions; reject broader
autonomous governance authority**.

## Current contract and quantitative capability

The closest human analogues are fund data steward, investment-operations
controller, and knowledge-system owner. It is not a partner, compliance officer,
database administrator with discretionary SQL, or research analyst.

Version 2 gives this agent 16 skills—the largest specialist surface—and the only
specialist `exec` permission. It may invoke two immutable launchers, seven
read-only `vcops` commands, and four fixed workflows. Its tool timeout is 120
seconds although the runner permits 360 seconds. It cannot browse, delegate,
edit, send, approve, or use arbitrary shell/SQL. Those restrictions, optimistic
revision checks, idempotency keys, and verified returned identifiers are strong
and should remain.

The role is nevertheless internally contradictory. It is called on to persist,
compile truth, inspect health, lint governance, run evals, check the resolver,
classify signals, propose schema, and audit notifications. Several advertised
maintenance commands do not exist in agent mode, and many specialist
`persistence_request` outputs terminate at operator-only paths. The agent is
configured as `VC_FAST_MODEL` even though its risk and skill count are highest;
both model tiers currently resolve to the same model, so the label has no
quantitative meaning.

## What top operating and practitioner practice contributes

### 1. Lineage before fluency

The W3C PROV model distinguishes an entity, the activity that generated or used
it, and the responsible agent. That is a useful structural analogy for facts,
workflow runs, artifacts, and actors
([PROV-O](https://www.w3.org/TR/prov-o/), grade A for provenance structure).
It supports Version 2’s strongest idea: an assertion is not durable evidence
unless the system can trace the source, operation, actor, and time.

The transfer is limited. PROV-O is an interchange model, not a complete fund
data model or permission system. Version 3.0 should retain explicit lineage but
not import an ontology wholesale.

### 2. Preserve valid time and recorded time

Bitemporal research separates when a fact was valid in the modeled world from
when it entered the database
([Clifford & Isakowitz](https://archive.nyu.edu/jspui/handle/2451/14356?mode=simple),
grade B). This supports the existing observed/source/valid-time fields and the
append/supersede approach. It also shows why retrieval ordered only by
`created_at` is wrong for current truth.

The literature is old and general; it does not decide which VC facts require
which temporal semantics. The agent needs explicit per-fact policy rather than
temporal fields added indiscriminately.

### 3. Entity resolution is candidate generation plus governed decision

Duplicate-record research treats entity resolution as uncertain record linkage,
not a string-equality side effect
([Duplicate Record Detection survey](https://archive.nyu.edu/jspui/handle/2451/27823),
grade B). PostgreSQL’s `pg_trgm` supplies indexed similarity and a 0–1 score,
but the documentation makes no identity claim
([PostgreSQL 17 `pg_trgm`](https://www.postgresql.org/docs/17/pgtrgm.html),
grade A for mechanism, C for identity policy).

The system should therefore use exact stable keys first, use aliases and fuzzy
scores to produce reviewable candidates, and never auto-merge on textual
similarity. This is also the practical human pattern in investment operations:
normalize, reconcile, document the exception, and require a controlled owner
decision for identity changes.

### 4. Small, deterministic interfaces beat discretionary repair

Amazon’s Type 1/Type 2 distinction is only a practice exemplar, but it captures
an important control mechanism: irreversible decisions deserve a different
path from reversible ones
([2016 shareholder letter](https://www.aboutamazon.com/news/company-news/2016-letter-to-shareholders),
grade C for this role). Version 2 already expresses this well: previews may be
agent-facing; destructive, merge, schema, approval, and external effects remain
operator-facing.

## Counterevidence and failure modes

- A perfect audit trail can faithfully preserve bad identity decisions. Lineage
  does not replace validation.
- Fuzzy search can increase recall while creating costly false merges,
  especially for common short names and multilingual aliases. Similarity is a
  candidate feature, not a decision.
- A single “steward” that owns checks, proposals, writes, and health creates a
  segregation-of-duties illusion. Prompt prohibitions do not make unavailable
  commands callable or self-review independent.
- More schema can lower data quality when agents fill fields merely because
  they exist. Additive fields need a downstream query and owner.
- Fund operations differ from adversarial multi-tenant systems. The current
  single-organization boundary supports simpler controls but does not justify
  cross-channel disclosure.

## Changes and causal mechanism

1. **Narrow the agent to deterministic lookup, preview, fixed workflow request,
   and verification.** Remove governance lint, signal detection, quiet-hours,
   research depth, and broad schema-design skills from its default allowlist.
   This reduces prompt conflict and the blast radius of the only exec-capable
   specialist.
2. **Make unavailable routes explicit.** Every persistence proposal must say
   `fixed_workflow`, `operator_only`, or `unsupported`; no dead-end implication
   that the steward can write a record.
3. **Reconcile timeout.** The outer allowed exec timeout must be at least the
   fixed runner cap plus bounded cleanup, or the runner cap must be lowered.
   A test must exercise the boundary rather than only compare constants.
4. **Add a governed entity-resolution lane.** Typed exact lookup, alias/domain
   tables, reviewable fuzzy candidates, immutable resolution decision, and an
   atomic resolve-or-create workflow make the advertised memory gate real.
5. **Generate schemas from one manifest.** Output/handoff enums should not drift
   across prose, skill, config, fixtures, and database helpers.
6. **Keep model judgment out of deterministic transforms.** Hashes, numeric
   normalization, score arithmetic, revisions, idempotency, and claim-location
   binding should be code results that the agent verifies, not recreates.

## Rejected imports

- Free-form SQL “for flexibility”. It defeats the reviewed boundary.
- Embedding similarity as automatic identity or fact authority.
- A universal enterprise master-data platform. It exceeds this published
  single-organization example’s needs.
- Autonomous schema migrations, merge approval, deletion, retention purge, or
  notification delivery.
- Making the steward an independent auditor of its own writes. Deterministic
  checks and operator review must remain distinct.

## Transfer limits

Biotech, regulated financial, defense, and multi-fund deployments require
additional retention, access, person/entity, export-control, and audit policy.
European deployments need purpose and confidentiality enforcement at retrieval,
not only at storage. The proposed resolver works for company/lead identity; it
does not authorize personal profiling or construct a universal CRM.

## Precommitted eval mapping

- 1,000 malformed invocation/property cases: 100% denial outside exact
  binaries/subcommands.
- Idempotency, revision conflict, rollback, terminal-state, and uncertain-timeout
  parity: 100%.
- Exact entity keys: 100% precision/recall; aliases at least 95%; fuzzy candidate
  recall/precision at least 90%; automatic fuzzy merges zero.
- Both intake workflows block unresolved identity review; no ignored lookup.
- Retrieval never exposes disallowed confidentiality and never promotes
  stale/submitted/contradicted facts to current.
- Every successful write returns committed IDs, revision, idempotency key, and
  verification; unverified success claims zero.
- The 360-second boundary and cleanup path receive a real end-to-end test.

These tests measure the mechanism. Adding richer prose without making retrieval
and workflow gates executable fails the dossier’s change gate.
