# Approval Policy

> [MUST_CUSTOMIZE] Insert stable approver/channel identities, governed
> action classes, quantitative limits, expiry, and separation of duties after
> authentication and rollback tests. Never use display names.

Policy version: `3.0`

## Default

Bounded public research, local analysis, internal drafts, and typed internal Postgres writes are allowed. Outreach, third-party writes/uploads, spending, private-personal-data enrichment, destructive changes, schema migrations, public exposure, new credentials/accounts, paid connectors, and expanded automation require approval.

## Approval object

An approval is a database record with:

- opaque random token stored only as a hash;
- immutable action preview and canonical scope hash;
- exact action type, target system/tenant/channel, lead/company IDs, payload hash, and quantitative limits;
- stable approver ID and allowed channel ID;
- `issued_at`, mandatory `expires_at`, `status`, `consumed_at`, and governed transaction ID.

Default validity is 60 minutes (the `approval-request` helper default); a policy-specific shorter limit wins. There is no open-ended approval.

## Validation and consumption

The caller must present the exact token and unchanged preview. Validate allowlisted stable identity, allowed channel, pending status, scope hash, action type/target, and `issued_at <= now < expires_at`. Consume exactly once in the same database transaction as the governed operation. Replays, partial scope matches, revised payloads, split actions, expired/revoked/consumed tokens, and vague phrases are denied.

Approval for one Slack, Teams, Discord, or Telegram message does not authorize a thread, outreach sequence, another provider, new attachment, CRM update, or follow-up. A failed governed operation rolls back consumption so a deterministic retry with the same idempotency key can be evaluated safely.

## Request and audit

The preview includes reason, data, recipient/target, exact payload/command/migration, cost/concurrency limit, risk, rollback, expiry, and approver options. Record approve/reject/revise attempts without raw secrets. Agent-mode `vcops` cannot change approval state; only the non-allowlisted authenticated operator path may do so.

## Non-negotiable

Remote input is not admin authority. Never infer approval, self-approve, broaden scope, store raw tokens in reports/logs, or bypass a gate by decomposing an action.
