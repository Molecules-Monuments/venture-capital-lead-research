# Channel Policy

> [MUST_CUSTOMIZE] Select one channel, stable sender/destination IDs, and
> authenticated approval path only after its live acceptance matrix passes.

Policy version: `3.0`

An allowlisted inbound message may receive one ordinary response in its same
provider conversation through OpenClaw's normal channel reply path. That narrow
response is not approval for a proactive message, new destination/thread,
other provider, outreach sequence, attachment, connector write, or later
follow-up. Version 3 does not ship a proactive notification dispatcher.

## Boundary

`vc-chief` is the only channel-facing agent. Specialists return packets to the chief. Stable tenant/workspace, account, channel, and sender IDs are allowlisted; display names are never authorization. Require mention in group channels. Direct-message access uses explicit allowlists. Channel-originated config writes and remote admin commands are disabled.

Slack, Teams, Discord, and Telegram are separate optional deployment overlays. Render exactly one primary end-user channel per deployment. Slack uses Socket Mode and one gateway connection; Teams uses a TLS reverse proxy to the loopback `/api/messages` webhook; Discord uses one Gateway bot with stable numeric snowflakes; Telegram uses one long poller and numeric user/group IDs. Connector secrets come from SecretRefs/environment, never this file.

## Permitted messages

Allowed users may submit leads, request internal research or a memo, ask status,
and attach a supported PDF, PPTX, XLSX, or CSV. Every message first receives a
trust decision. The trusted-context plugin binds the configured account, stable
sender ID, event, session, and exact staged media paths into a short-lived
scoped capability. The deterministic document workflows verify, snapshot,
extract, and associate the artifact before research; document content remains
untrusted and cannot grant authority. Approval decisions and bearer tokens are
never accepted through a channel message.

Multiple allowlisted users share one gateway but receive `per-channel-peer`
direct-message sessions and separate Postgres preference principals keyed by
provider, account, and sender ID. Group/channel conversations require a mention
and may read a sender's preferences but never learn or forget persistent
preferences. This is user separation for one reviewed organization, not hostile
multi-tenant isolation.

## Prohibited messages

Remote channels cannot change configuration, secrets, tool policy, network exposure, cron, schema, or agent allowlists. They cannot directly address specialists or turn document/message content into instructions.

## Approval boundary

Channel text may request or discuss a preview but cannot decide or consume it.
The authenticated host-operator path must bind the immutable preview,
lead/action IDs, exact opaque token, scope, expiry, and durable audit. Human
chat text itself is never authority.

## Smoke gate

Before production: confirm stable IDs/allowlists, mention behavior, DM isolation, config/admin/approval surfaces disabled, unknown sender denial, supported attachment acceptance, malicious/unsupported attachment rejection, duplicate-event idempotency across restart, preference separation/forget behavior, provider acknowledgement, and no specialist binding. The selected provider must pass every applicable row in `docs/CHANNELS.md`; `NOT RUN` is not a pass. Teams group/channel file retrieval that requires Graph/SharePoint permissions is a separate optional integration and must be commissioned explicitly; Teams personal/DM attachments supported by the selected adapter are the default tested lane.
