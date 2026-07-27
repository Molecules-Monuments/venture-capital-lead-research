# Notification and Quiet-Hours Policy

> [MUST_CUSTOMIZE] Review recipients, quiet hours, content minimization,
> approvals, and delivery retention. This release does not authorize proactive
> outreach or imply a delivery dispatcher exists.

Policy version: `3.0`

Default timezone is `Europe/Berlin`. Normal delivery is Monday–Friday, 08:00–19:00 local time; configured holidays and all other times are quiet.

## Severity and state

| Severity | Behavior |
|---|---|
| `silent_log` | Persist only; never dispatch |
| `batched` | Join next scheduled digest |
| `normal` | Queue now or hold until next permitted window |
| `urgent` | Bypass only for a listed category and valid approval when policy requires |

Urgent categories are security/data exposure, production failure blocking all intake, a same-day blocking contradiction on a partner-review lead, or an approval that expires before the next window.

The data model can represent this future lifecycle:

`draft -> queued|held -> attempted -> delivered|failed`, with `cancelled` terminal where applicable.

Creating an outbox record is not delivery. Version 3 ships no proactive
dispatcher or digest scheduler and permits only operator-created
`internal_log` records. A future dispatcher would require its own reviewed
identity, destination allowlist, idempotency/retry implementation, and live
hard gate. Never label `queued`, `held`, or `attempted` as sent.

## Required record

Store provider/account/destination stable IDs, subject/body hash, severity, related lead/workflow/approval IDs, timezone/policy version, `deliver_after`, idempotency key, attempt count, last error class, provider message ID, and timestamps. Do not place approval tokens, raw secrets, private document content, or unnecessary personal data in notifications.

No agent or `vcops` command in this release proactively sends: agent-mode
`vcops` is read-only and the chief may only classify or propose.

**Proactive delivery is a native OpenClaw capability, not a custom one.** When
an operator wants a scheduled digest (e.g. after a source scan), it is delivered
by a native cron job with `delivery.mode: "announce"` over the durable outbound
queue — configured with `openclaw cron add` (see `CUSTOMIZATION.md`), gated by
the approval policy for frequency/concurrency. The `notification_outbox` SQL
lifecycle (claim/dispatch/retry/receipt) is **superseded by that native queue
and is not driven by this release**; only the internal-log record is written by
`vcops notification-enqueue`. Same-thread channel replies are governed
separately by `channel_policy.md`.
