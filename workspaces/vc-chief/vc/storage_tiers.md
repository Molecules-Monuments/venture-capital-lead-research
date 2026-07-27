# Storage Tiers

> [MUST_CUSTOMIZE] Map every confidentiality/retention class to reviewed
> local storage, encryption, backup, processor, access, and deletion controls.

Policy version: `3.0`

| Tier | Content | Rule |
|---|---|---|
| `operational` | Task Flow/Lobster/OpenClaw operational state | Not business authority; bounded retention |
| `research` | Public URLs, normalized typed evidence, internal drafts | Postgres/source-linked; least privilege |
| `confidential` | Submitted decks, non-public metrics, restricted notes | Encrypted host storage, stricter access/retention |
| `quarantine` | Untrusted or failed documents | Non-executable, parser-only path, no channel/model authority |
| `audit` | approvals, workflow state, notification attempts, migrations | Append-oriented and retention-protected |

Secrets are never a storage tier; they live in configured SecretRefs/environment and are excluded from reports, workspace memory, Postgres evidence, and artifacts. Raw uploads are separated from extracted claims. A policy assigns tier/confidentiality/retention before persistence.
