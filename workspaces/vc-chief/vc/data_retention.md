# Data Retention

> [MUST_CUSTOMIZE] This file records whatever purpose, lawful basis,
> retention, deletion, legal-hold, processor, backup and restore policy your
> firm determines. The periods below are examples with no automated enforcement
> behind them. These are legal determinations, not software settings — ask your
> counsel if any of them are in doubt.

Policy version: `3.0`

Collect the minimum lawful data needed for lead research. Default retention:

| Class | Default |
|---|---:|
| Public research evidence and decision audit | 24 months |
| Internal drafts and superseded snapshots | 12 months |
| Submitted confidential originals/extractions | 12 months or client instruction, whichever is shorter |
| Quarantined/failed uploads | 30 days |
| Notification payloads | 90 days; delivery metadata 12 months |
| Approval and migration audit | 24 months |
| Task Flow/Lobster operational state | 90 days after terminal state |

Legal hold, contract, consent, or client policy may change a period and must be recorded. Do not retain raw secrets, unnecessary personal contact data, document text in logs, or duplicated channel payloads. OpenClaw conversational Markdown memory is disabled by default; do not enable it as an archival shortcut.

## Enforcement (Version 3.0)

Two mechanisms enforce retention deterministically; the narrative time-based
periods for product data (24mo/12mo/90d/30d) have **no automated purge
executor in 3.0** and are operator-run procedures until deterministic purge
tests pass (see the banner above):

- **Harness data** (conversation sessions, transcripts, logs) is governed by
  native OpenClaw config in `config/openclaw.json`, which has real executors:
  `session.maintenance` (`mode: enforce`, `pruneAfter`, `maxEntries` — enforced
  on session-store writes and by `openclaw sessions cleanup`; reads and Gateway
  startup never prune, so a quiescent deployment needs the on-demand cleanup
  command for `pruneAfter` to take effect) and
  `logging.maxFileBytes` (log rotation). Tune these keys to the periods above.

  **Put that cleanup on the operator's weekly list — nothing in the package
  runs it for you.** `scripts/schedule_jobs.sh` seeds `vc-source-scan` and
  `vc-heartbeat` only, and the optional `cron` opt-in adds neither this command
  nor a schedule for it, so a deployment (or a single per-agent store) that
  goes quiet retains transcripts past `pruneAfter` until someone runs:

  ```sh
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw sessions cleanup --all-agents --dry-run
  docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
    exec openclaw-gateway openclaw sessions cleanup --all-agents
  ```

  `--all-agents` is load-bearing: without it the command maintains only the
  configured default agent's store, and the other agents' transcripts age past
  the configured period unnoticed. Run the `--dry-run` form first — it prints
  what would be pruned without writing.
  (The generated-media `media.ttlHours` sweep is intentionally not enabled: it
  prunes empty directories including the workflow inbound-media root. Inbound
  document snapshots are product data, retained by the product operation below.)
  Turning the optional `cron` job on brings one further retention key into
  scope, unset in `config/openclaw.json` today: the completed session each cron
  run leaves behind is pruned by `cron.sessionRetention` (harness default:
  `24h`), which fires sooner than `session.maintenance.pruneAfter`. Set it to
  the firm's period in the same edit that sets `cron.enabled: true`.

  Cron run history is **no longer a retention decision you can make**. On the
  `2026.8.1` base the `cron_run_logs` table is gone — opening the state
  database migrates its rows into `task_runs` and drops it — and
  `cron.runLog.keepLines`, which used to bound it, is retired with no
  replacement (upstream's own migration note records the fixed retention as
  2000 runs per job). Those rows carry each run's reply text, they live in the
  persistent `openclaw-state` volume, they ride into every recovery point, and
  `openclaw sessions cleanup` does not prune them. Treat that as a fixed-size
  store outside the firm's period rather than as something to tune, and size
  the retention narrative around it.
- **Product data** (companies, leads, facts, evidence, memos in Postgres) is
  governed by the reviewed, approval-gated `vcops data-erase-lead` operation
  (operator lane). It consumes a scoped one-time approval in the **same
  transaction** as the erasure (SECURITY DEFINER `consume_approval_and_erase_lead`),
  so an erasure cannot occur without a matching approval. Because the schema uses
  `ON DELETE RESTRICT`, erasure is by supersession/tombstone — the lead's facts
  are retracted and the lead archived, never raw-DELETEd — preserving the minimum
  lawful audit record (`audit_events` kind `data.erasure`). Subject-erasure and
  legal-hold-expiry requests run through this path.

  **What the operation does and does not remove.** Since migration 017 the
  retraction tombstone is written with NULL value columns and
  `value_kind='unknown'`, so the operation no longer duplicates the subject's
  values into a second row. The **superseded original rows remain**: `facts` is
  append-only by trigger and no role may UPDATE or DELETE it, so the pre-erasure
  values stay in the table until an owner-run out-of-band procedure removes
  them. The erasure transaction writes only `facts` (the tombstones), `leads`
  (`status`), `audit_events` (two rows: the approval consumption and the
  erasure), and the consumed `approvals` row's bookkeeping columns — and on
  `leads` it changes `status` alone, so the archived row's other columns
  survive verbatim: `submitted_claims`, `lead_title`, `origin_note`,
  `referrer_name`, `referrer_organization`, `submitted_by`, and the
  channel-identity columns (`channel_account_id`, `channel_event_id`,
  `channel_message_id`, `channel_sender_id`, `channel_permalink`). Every
  other value-bearing store
  is **not** covered and is an operator-run step. The complete list — enforced
  against `docs/SCHEMA.sql` by `tests/v3/test_erasure_gap_enumeration.py`,
  which fails whenever the regenerated schema reference gains a table nobody
  has dispositioned:

  - `workflow_requests` — `request_payload` is the canonical intake payload
    (company name and domain, lead title, document path, channel
    identifiers), append-only by trigger, so every original submission
    survives verbatim;
  - `compiled_truth.fact_history` **and `compiled_truth.current_view`** —
    the snapshot keeps the erased values verbatim, keyed by fact type and
    definition;
  - `memos` (including `content_uri` and the rendered memo body) and
    `memo_citations`;
  - `lead_artifacts`, `evidence_artifacts`, `document_extractions` — the
    stored documents and their extracted content;
  - `sources` — a subject's own uploads register rows whose `title`,
    `canonical_uri`, `publisher`, and `metadata` identify the document;
  - `evaluations` and `evaluation_criteria` (per-criterion `rationale`
    text);
  - `fact_sources`;
  - `contradictions` (`explanation`), `trajectory_events` (`calculation`),
    `orchestration_audit` (`payload`), `notification_outbox` (`subject` and
    `payload`);
  - `workflow_runs` (`result`, error and cancellation text) and `proposals`
    (`title`, `summary`, `content`) — both lead-keyed;
  - `approvals` — the row itself is governance audit and is retained
    deliberately, but `scope`, `action_preview`, and `decision_note` can
    embed the governed action's subject data and are in scope for a sweep;
  - `entity_resolution_runs` (`identity_query` holds the submitted identity
    verbatim), `entity_resolution_decisions` (`reasons` and candidate
    lists), and `entity_resolution_consumptions`;
  - the company identity rows themselves — `companies`, `company_domains`,
    `company_aliases`, `company_external_ids`; and
  - the child linkage and locator rows that follow their listed parents:
    `compiled_truth_facts`, `contradiction_facts`, `trajectory_points`,
    `document_facts`, `notification_attempts`.

  Channel-user identity and preference memory (`channel_principals`,
  `user_preferences`, `preference_observations`, `preference_forget_markers`,
  `user_preference_audit`, `trusted_context_uses`) are a separate
  personal-data lane scoped to channel principals, not leads; its
  subject-request path is the `preference-forget` workflow, not
  `data-erase-lead` — and like the erasure operation it deletes nothing.
  `preference-forget` writes an append-only forget marker and audit row and
  NULLs only the current `user_preferences` value (status `forgotten`); as
  part of consuming its capability it also UPSERTs the subject's
  `channel_principals` identity row and appends a `trusted_context_uses` row.
  Four of the six (`trusted_context_uses`, `preference_observations`,
  `preference_forget_markers`, `user_preference_audit`) are append-only by
  trigger, which refuses UPDATE and DELETE for every role — including
  `openclaw_owner` — until the owner disables the trigger.
  `channel_principals` and `user_preferences` have no such trigger: the runtime
  role holds only SELECT/INSERT/UPDATE on them and no shipped code path issues
  a DELETE, but `openclaw_owner` owns the tables and can remove rows directly.
  Either way the historical preference values (`preference_observations`),
  channel identity (`channel_principals`), and capability-use rows survive
  verbatim until an owner-run out-of-band step — document and rehearse that
  user-lane step alongside the lead-lane gaps listed above. The
  operational registries `schema_migrations` and `fact_promotion_policy` hold
  no subject data; `signal_sources` rows describe operator-registered watched
  sources rather than lead submissions, but a watch registered specifically
  about the subject (its `source_name`, `canonical_uri`, or `metadata` naming
  the company) belongs in the erasure sweep — check the watchlist. Treat
  `vcops data-erase-lead` as the audited entry point to an erasure procedure,
  not as a complete right-to-erasure executor — and treat `preference-forget`
  the same way for the channel-user lane. What each one does not reach is
  listed above, and covering those gaps is outside the software; document and
  rehearse the out-of-band steps for both lanes before a deployment relies on
  either path.

### The erasure guarantee is PostgreSQL-scoped

The enumeration above is complete **for PostgreSQL and for nothing else.** It
is derived from `docs/SCHEMA.sql` and enforced against it by
`tests/v3/test_erasure_gap_enumeration.py`, so a new PostgreSQL table cannot
slip past it — and by exactly the same construction, a store that is not a
PostgreSQL table is invisible to it. The harness keeps a subject's words in
several such stores. Read this list as the boundary of the guarantee, not as a
second gap list with a test behind it:

- **The full-text index of every message, which cannot be turned off.** Each
  agent's `openclaw-agent.sqlite` carries `session_transcript_fts`, an FTS5
  virtual table created without a `content=` option, so SQLite keeps a
  **verbatim second copy** of every user and assistant message in its own
  shadow table. It is created unconditionally as part of the agent schema:
  there is no configuration key for it anywhere in the `2026.8.1` runtime, and
  it did not exist at all on `2026.7.1`. Personal data planted in a
  conversation was read back out of the index directly. Message text therefore
  lives in three places at once — `transcript_events.event_json`,
  `session_transcript_archives.archive_blob`, and that index — and an erasure
  procedure that reaches only one of them has not erased anything. The
  surrounding tables (`session_transcript_active_events`,
  `transcript_event_identities`, `session_transcript_index_state`) hold
  positions and identifiers rather than text and cascade from
  `transcript_events`.
- **Session deletion and pruning are archival, not erasure.** After
  `openclaw sessions delete` reports `"status":"deleted"`, a compressed archive
  file *and* a `session_transcript_archives.archive_blob` row both persist, and
  the deleted plaintext is still recoverable from the live `.sqlite` and its
  `-wal` sidecar: the database runs with `secure_delete=0`, so freed pages keep
  their contents. `scripts/backup.sh` captures all of it. The only
  residue-removing mechanism measured here was taking a VACUUMed copy —
  `openclaw backup sqlite create` — after which the planted strings were gone.
  A deployment that must *erase* rather than *retire* a transcript needs that
  step written into its procedure; nothing runs it for you.
- **The harness retention keys are eight, not four.** `session.maintenance`
  accepts `mode`, `pruneAfter`, `archiveDashboardAfter`, `maxEntries`,
  `preserveRecent`, `resetArchiveRetention`, `maxDiskBytes` and
  `highWaterBytes`. Only the first, second and fourth are set in
  `config/openclaw.json`. `resetArchiveRetention` and `maxDiskBytes` matter on
  the `2026.8.1` base in a way they did not before: `resetArchiveRetention`
  stopped inheriting `pruneAfter` and now keeps reset archives until the disk
  budget evicts them, and that eviction lane runs behind `cron.enabled`, which
  is off here. Unset means "kept", not "pruned with everything else".
- **Derived memory outside any database.** Each workspace can accumulate a
  `MEMORY.md` and, if the memory plugin's dreaming lane is ever enabled, a
  `DREAMS.md`. They are plain files on the state volume, they are captured by
  backup, and no erasure path touches them. This release pins dreaming off, so
  the second file should not appear — check for it rather than assuming.
- **Per-agent memory tables.** `openclaw-agent.sqlite` also holds
  `memory_index_chunks`, `memory_index_chunk_provenance` (new in `2026.8.1`,
  recording an origin class and session kind per chunk),
  `memory_index_chunk_recall_metadata`, `memory_index_sources`,
  `memory_index_meta`, `memory_index_state`, `memory_embedding_cache` and
  `memory_entry_origins`. Memory search is disabled in this release, which
  stops chunks being *retrieved*; it is not a promise that nothing was ever
  written.

Two consequences for the policy this document records. A subject-erasure
commitment that is not qualified will be wrong: state the guarantee as
PostgreSQL-scoped and describe the harness stores as an operator-run procedure,
the way the PostgreSQL gaps above are already described. And widening
`tests/v3/test_erasure_gap_enumeration.py` past `docs/SCHEMA.sql` — so the
harness stores get a closed world of their own — is deliberately **not** done
in this release; until it is, this section is prose backed by measurement
rather than by a gate, and it needs re-checking against each upstream bump.
