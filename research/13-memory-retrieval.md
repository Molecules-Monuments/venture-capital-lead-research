# Memory and Retrieval Research Audit

Access date for web sources: 2026-07-20. Verdict: **Version 2 retrieval does
not meet its documented contract**.

## Two systems with different authority

Version 2 calls both of these “memory”:

1. `vcops memory-lookup`: authoritative Postgres retrieval.
2. OpenClaw `memory_search`/`memory_get`: non-authoritative per-agent Markdown
   recall using memory-core.

The distinction in policy is correct; their implementation and routing are not.

## Authoritative Postgres coverage

The skill and `vc/memory_lookup.md` promise IDs, normalized domains, legal/name
aliases, people, URLs, artifact hashes, stable source/message keys, typed
evidence, decisions, workflow audit, exact-first search, fuzzy candidates,
staleness, method, confidence, and a research/create decision.

Actual `cmd_memory_lookup` performs only:

- company `name ILIKE '%query%'` or exact `canonical_domain`;
- lead `lead_title ILIKE '%query%'`;
- newest associated facts ordered by `created_at`;
- constant `external_research_allowed: false`.

There is no ID equality, legal-name lookup, alias/person/relationship table,
artifact SHA, source/channel key, memo/evaluation/workflow result, fact-source
join, stale/current resolution, method, score, confidence, merge candidate,
reason, or next step. `%` and `_` are not escaped, so wildcard input can
enumerate recent records. A combined recency limit can omit an older exact
domain match. Leading-wildcard `ILIKE` also does not implement fuzzy identity
and does not use the simple lower-name index efficiently.

The schema already contains useful exact keys—company domain, provider event,
stable source ID/URI, artifact hash—but lookup ignores them. `legal_name` is
stored but not searched. The contracts mention aliases and relationships that
do not exist.

## The creation gate is not enforced

The outbound fixed workflow calls memory lookup but no later step consumes its
result; it proceeds to company upsert. The inbound workflow never calls lookup.
Therefore 0 of 2 create paths enforce the promised resolution decision. The
exact-domain unique index prevents one duplicate class, but renamed companies
raise an identity conflict for which no reviewed change operation exists, and
null-domain names can duplicate.

Only the data steward can execute the authoritative helper. The router and
research agents that “own” lookup have only Markdown memory tools. A safe
orchestration can spawn the steward first and pass its packet to the router, but
the current resolver does not make that deterministic predecessor explicit.

## OpenClaw operational recall

The pinned memory-core searches only `MEMORY.md`, `memory/*.md`, and optionally
session transcripts. Version 2 seeds none. Every agent workspace is image-owned
read-only; only the chief’s `memory/` directory has a writable named volume.
Thus 11 specialists expose search over an initially empty, read-only corpus.

Automatic pre-compaction flush is enabled. The pinned writability check treats
unsandboxed workspaces as writable without inspecting filesystem permissions.
Because sandbox mode is off, chief flush can append to its mounted directory,
while specialist flush is expected to fail against the read-only image. No
health check exercises this.

Defaults also mean semantic/hybrid search can send chief notes to the configured
embedding provider, MMR and temporal decay are disabled, session indexing is
disabled, and each agent has a separate SQLite index. This may support chief
operational recall after compaction; it is not Postgres retrieval.

## Privacy, retention, and poisoning

Non-session Markdown hits have no peer/channel visibility filter. A chief note
derived from one channel peer can therefore appear in another chief session,
despite per-channel-peer session scope. The Postgres lookup has no requester,
purpose, tenant, or allowed-confidentiality arguments and can return fact values
without joining lead/source/artifact confidentiality.

The deployment is single-organization, not hostile multi-tenancy, but
need-to-know and confidentiality still apply. Narrative retention policy is
not a purge mechanism: only artifacts carry explicit retention class; cron is
disabled; chief Markdown and its indexes are backed up; lookup has no expiry
filter.

Remote text, recalled notes, and database values are untrusted content. A
recalled note cannot establish authority, approval, identity, or successful
persistence. NIST defines prompt injection as concatenating untrusted input
with higher-trust prompts
([NIST definition](https://csrc.nist.gov/glossary/term/prompt_injection)); the
correct control is authority separation and minimal tool scope, not a promise
that the model will always ignore content.

## Research-informed Version 3.0 design

### Rename the concepts

- **Entity resolve:** authoritative Postgres identity/current-state retrieval.
- **Operational recall:** sanitized, non-authoritative preferences and handoff
  notes.

This prevents one tool’s semantic search quality from being mistaken for the
other’s business authority.

### Staged entity resolution

1. Typed exact company/lead/external/source/message/artifact IDs.
2. Exact verified domain relationships.
3. Current legal/trade/former-name aliases.
4. Explainable token/FTS and trigram candidate generation.
5. Optional semantic retrieval only to discover candidates.
6. Join current facts, sources, prior decisions, open contradictions, and
   freshness.
7. Apply requester purpose and confidentiality before values leave the helper.

PostgreSQL documents trigram similarity and index support
([`pg_trgm`](https://www.postgresql.org/docs/17/pgtrgm.html)); duplicate-record
research documents why uncertain linkage needs separate matching and decision
stages
([survey](https://archive.nyu.edu/jspui/handle/2451/27823)). Neither justifies
automatic merge.

Add `entity_aliases`, `company_domains`, `entity_external_ids`,
`merge_proposals`, and immutable `entity_redirects`, each with provenance,
validity, status, and confidence. Normalize Unicode deliberately and domains
with IDNA-aware logic; preserve apex/`www` relationships until redirect or
ownership evidence exists.

Resolver output should be a persisted, expiring decision: `existing`,
`new_allowed`, or `review`, with query hash, policy version, candidate set, and
reason. `company-resolve-or-create` must consume the matching decision in the
same transaction. Expiry, replay, input mismatch, or candidate drift fails.
Inbound and outbound both use it; workflow validation rejects an unused lookup.

### Operational recall policy

Safest default for the published example:

- disable automatic flush unless a sanitized-memory lane is deliberately
  enabled;
- remove memory tools from specialists with empty corpora;
- allow chief notes only for operator preferences, run IDs, handoff state, and
  non-sensitive operating decisions;
- never store lead facts, documents, contact data, secrets, or approval material;
- make embedding provider, allowed confidentiality, retention, cost, MMR, and
  temporal behavior explicit;
- attach provenance, audience, confidentiality, and expiry, or use a structured
  store when cross-channel recall is required.

Plain Markdown cannot enforce field-level access control. If a deployment needs
cross-channel confidential memory, it needs structured retrieval-time audience
checks rather than a longer prompt.

## Why the Version 2 gates gave false confidence

This section assesses the **Version 2** gate set as it stood at the audit date;
it is the finding that motivated the retrieval gate Version 3.0 went on to
build, not a statement about the shipped release. At that time: no retained
test invoked `memory-lookup`; the G4 database suites tested strong workflow
invariants but not retrieval; G5 was static and could not detect that the
outbound workflow discarded lookup; G8 tested memory survival, not indexing,
precision, isolation, specialist flush, or expiry. Offline “PASS” was valid
only for those tested surfaces and could not be presented as retrieval
acceptance.

> **Closed in Version 3.0** (note added 2026-08-06; the section above keeps its
> original finding for provenance). Every limb of it was answered in the
> shipped package:
>
> - `scripts/verify_offline.py` registers `tests/retrieval` as a gate step, so
>   retrieval is no longer outside the offline gate.
> - `tests/retrieval/test_entity_resolution_contract.py` inspects
>   `vcops.cmd_memory_lookup` directly, and asserts that both creation
>   workflows order `workflow_request_claim` → `company_resolve_create` →
>   `create_lead` with no `memory-lookup` call — the exact bypass this section
>   identified as undetectable by a static gate is now the assertion.
> - The precommitted thresholds below were executed as gate D on the
>   declared 100k-company/1m-fact reference dataset via
>   `scripts/run_retrieval_scale.py`. (The p95 ceiling is Gate D's; Gate I
>   covers research budgets, whose adherence half stays BLOCKED.)
>
> The design half of this document — staged entity resolution and the disabling
> of Markdown recall as a factual store — shipped in
> `migrations/006_entity_resolution.sql` and the resolver helpers.

## Precommitted retrieval eval

Use real disposable Postgres state and judged queries. NIST TREC’s core model—
frozen corpus, queries, relevance judgments, and comparable runs—is appropriate
([TREC evaluation](https://trec.nist.gov/howto.html),
[relevance judgments](https://trec.nist.gov/data/reljudge_eng.html)).

Required cases include exact IDs/domains/URL/hash/source/message/permalink;
former and trade names; rename on same domain; same name/different domain;
typo/acronym; mixed-script/zero-width/wildcards; stale/superseded/contradicted
facts; prior decision; restricted requester; outage; concurrent create;
resolution replay/expiry/mismatch/drift; both workflows; empty memory index;
specialist compaction; expiry/legal hold and restore.

Thresholds: exact precision/recall 100% and MRR 1.0; alias recall at least 95%
(99% target); fuzzy duplicate recall@5 at least 95% with zero automatic merges;
no unauthorized leakage; no stale-as-current; no workflow bypass; no concurrent
duplicate; 100% output schema; exact p95 under 100 ms and fuzzy p95 under 250 ms
on the declared million-alias reference dataset.

Hybrid embeddings may later be compared using Recall@k, precision@k, MRR, and
nDCG. They are not required for Version 3.0 identity correctness, and long
context is not a substitute for retrieval—the “lost in the middle” finding is
a relevant caution
([Liu et al.](https://arxiv.org/abs/2307.03172)).
