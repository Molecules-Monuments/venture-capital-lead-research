# Data Retention

> [MUST_CUSTOMIZE] Obtain jurisdiction/client review for purpose, lawful
> basis, retention, deletion, legal hold, processor, backup, and restore rules.
> Narrative periods are not complete until deterministic purge tests pass.

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
  on session-store load and by `openclaw sessions cleanup`) and
  `logging.maxFileBytes` (log rotation). Tune these keys to the periods above.
  (The generated-media `media.ttlHours` sweep is intentionally not enabled: it
  prunes empty directories including the workflow inbound-media root. Inbound
  document snapshots are product data, retained by the product operation below.)
- **Product data** (companies, leads, facts, evidence, memos in Postgres) is
  governed by the reviewed, approval-gated `vcops data-erase-lead` operation
  (operator lane). It consumes a scoped one-time approval in the **same
  transaction** as the erasure (SECURITY DEFINER `consume_approval_and_erase_lead`),
  so an erasure cannot occur without a matching approval. Because the schema uses
  `ON DELETE RESTRICT`, erasure is by supersession/tombstone — the lead's facts
  are retracted and the lead archived, never raw-DELETEd — preserving the minimum
  lawful audit record (`audit_events` kind `data.erasure`). Subject-erasure and
  legal-hold-expiry requests run through this path.
