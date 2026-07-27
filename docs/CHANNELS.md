# Channel Profiles and Acceptance Gates

## Release contract

Version 3.0 supports one optional primary channel per deployment: Slack Socket
Mode, Microsoft Teams webhook, Discord Gateway, or Telegram long polling.
`PRIMARY_CHANNEL=none` is the distribution and rollback state.

A selected profile supports multiple users. Its `*_ALLOWED_USER_IDS` value is
a comma-separated list of at most 100 unique stable provider IDs. Display
names, usernames, email addresses, UPNs, forwarded text, and wildcards are not
authorization. `scripts/check_env.sh` rejects partial/unselected credential
families, invalid stable IDs, duplicates, empty list items, unknown profiles,
and an out-of-range attachment limit.

`scripts/render_channel_config.py` deep-merges only the selected strict overlay,
materializes list and destination sentinels, applies the configured model and
search providers, and writes `config/runtime/openclaw.json` atomically with
mode `0600`. A networkless initializer validates and copies that document to a
node-owned mode-`0400` named-volume file. Gateway and CLI mount it read-only.
Never edit the generated file; edit reviewed input, validate, render, and
force-recreate the gateway.

Only `vc-chief` on account `default` is channel-bound. No specialist has a
channel binding. Direct-message scope is `per-channel-peer`, so two allowed
users do not share the same direct session.

## Trusted user and attachment context

The image-owned `vc-trusted-context` extension observes channel-owned fields
and injects an opaque HMAC-authenticated capability into the matching chief
turn. The signed payload includes provider, account, sender, conversation,
session hash, run/event ID, DM/group classification, direct-child media paths,
scopes, random nonce, issue time, and a maximum 30-minute expiry.

The model cannot create or alter this capability. `vcops` verifies its exact
schema, signature, expiry, scope, media-root/path relation, and supported
provider. PostgreSQL binds use to the verified principal and consumes each
nonce/scope for one operation key. A different reuse fails as replay.

Preference changes are direct-message only. Unknown session shapes are treated
as group sessions and fail closed for preference writes/forgetting.

## Attachment boundary

All profiles set `mediaMaxMb` from `VC_CHANNEL_MEDIA_MAX_MB` (1–50 MiB).
Version 3's governed document lane accepts only PDF, PPTX, XLSX, and CSV.

OpenClaw can normally send image/audio/video attachments directly to a capable
reply model. The trusted extension therefore blocks any non-document attachment
kind and any normalized attachment path outside the four supported suffixes in
`before_agent_run`, before model input. The user receives a supported-format
message instead.

For a supported document:

1. OpenClaw stores it as a direct file under its private inbound-media root.
2. The extension signs the exact current-event path and operation scopes.
3. The chief sends that opaque capability only to data steward.
4. `document-ingest` verifies the path, type/signature, size, archive/XML,
   macros/active content, encryption, formula/resource limits, and hash.
5. It creates an immutable content-addressed snapshot and bounded extraction.
6. `document-extraction-show` and `document-lead-intake` require the same
   principal/path capability and preserve provider event/sender provenance.

Attachment content is untrusted submitted-claim data. It does not modify
policy or act as instruction. Text/table extraction can be incomplete and does
not promise OCR or chart/image/layout understanding.

The optional host-operator `/inbox` remains available for authenticated manual
operations, but channel users never need to copy files there. Channel
attachments must use `document-ingest`; `/inbox` `inbound-intake` rejects a
channel provider.

## Plugin provenance

- Slack: `@openclaw/slack@2026.7.1`.
- Teams: `@openclaw/msteams@2026.7.1`.
- Discord: `@openclaw/discord@2026.7.1`.
- Telegram: bundled plugin `2026.7.1`.
- Trusted context: image-owned project extension `3.0.0`.

The exact npm graph is locked in `runtime-packages/package-lock.json`. The G6
image gate verifies installed versions and validates every profile inside the
exact built image with networking disabled.

## Common activation sequence

1. Keep `PRIMARY_CHANNEL=none`; pass offline, database, and exact-image gates.
2. Create the provider application/bot and record stable provider IDs.
3. Fill only the selected credential/ID family and a reviewed comma-separated
   user list. Set `.env` mode `0600`.
4. Validate `.env` and customization, render config, and record its SHA-256.
5. Build the exact image; run config validate, doctor, security audit, channel
   inspect/status/probe, and provider-specific app checks.
6. Test each applicable matrix row below. Retain timestamps, config/image
   digests, redacted stable IDs, provider event IDs, database counts, and logs.
7. Resolve every warning. `FAIL`, `NOT RUN`, missing evidence, or an unexplained
   warning is not a channel pass.
8. Only then admit real messages. Rollback sets `PRIMARY_CHANNEL=none`, clears
   all channel families, rerenders, recreates, and proves no connection exists.

## Common live matrix

| ID | Test | Required result |
| --- | --- | --- |
| CH-01 | Exact plugin/image/config inspection and probe | Pinned plugin loads; no auth/schema/policy warning |
| CH-02 | First and second allowed-user DM; unknown-user DM | Both allowed principals route once to chief in different sessions; unknown denied |
| CH-03 | Same preference key for two allowed users | Values remain principal-isolated; neither appears in the other's lookup/output |
| CH-04 | Explicit preference, three inferred events, duplicate event, forget, group change | Exact activation thresholds; duplicate ignored; forget cutoff works; group change denied |
| CH-05 | Allowed mention, no mention, wrong user/destination | Only exact allowed mention activates |
| CH-06 | Remote config/admin/native command/approval/tool attempt | Every disabled surface denied |
| CH-07 | Supported PDF/PPTX/XLSX/CSV attachment | Signed path, deterministic extraction, lead association, location-preserving review |
| CH-08 | Image/audio/video, macro/legacy/encrypted/malformed/oversized/archive-bomb attachment | Unsupported media blocked before model; unsafe document rejected/quarantined; no lead/fact mutation |
| CH-09 | Same provider event before/after reconnect or restart | One logical turn/domain effect; replay does not create a second mutation |
| CH-10 | Network interruption and gateway restart | Bounded recovery; one active receiver; new event processed once |
| CH-11 | Reply delivery ambiguity/failure | No blind duplicate send; delivery state is reconciled or explicitly unknown |
| CH-12 | Rollback to `none` | No active channel, credentials, binding, or callback exposure |

## Slack Socket Mode

Use one Slack app and one Socket Mode connection per gateway. Supply distinct
`xoxb-...` bot and `xapp-...` app tokens and grant only scopes/events required
by the pinned [OpenClaw Slack guide](https://docs.openclaw.ai/channels/slack).
Allowed users are stable `U...`/`W...` IDs; the destination is a stable
`C...`/`G...` ID.

Inbound document use requires the Slack app's file-read capability (including
`files:read`) and the corresponding reviewed file/message events; a minimal
text-only Slack manifest will validate but cannot commission CH-07. Do not add
`files:write` unless the deployment separately chooses and reviews outbound
file sending, which this application does not require.

DMs are allowlisted. The selected channel is allowlisted, mention-gated, and
restricted to the same user list. Bot senders, name matching, native commands,
channel actions, unfurls, and native exec approvals are disabled. Thread
replies require an explicit mention. Slack-hosted files are best-effort;
thread-starter hydration may fail, in which case the user must attach the file
to the current request.

Add Slack-specific checks for token separation, exactly one Socket Mode
connection, WSS reconnect, thread starter/reply behavior, file-only starters,
and Slack event timestamp replay.

## Microsoft Teams webhook

Use stable Entra app/tenant UUIDs, one client secret, stable sender object
UUIDs, and exact Teams conversation IDs. The callback is `/api/messages` on the
loopback-published Teams port. A hardened TLS reverse proxy exposes only that
path; it must never expose the gateway/Control UI.

The profile disables delegated auth, SSO, welcome/feedback cards, name
matching, and config writes. DMs and groups use the same stable user allowlist;
team/channel messages are mention-gated.

OpenClaw supports text and personal/DM attachments. Teams channel/group files can
require Graph permissions plus `sharePointSiteId`. The shipped profile omits
both. Therefore:

- commission personal/DM attachments as the default supported Teams lane;
- expect a channel-file request to remain unavailable if Teams does not supply
  the bytes through the normal chat attachment path; and
- treat Graph/SharePoint channel-file retrieval as a separate privileged
  extension with independent app permission, tenant-consent, egress, privacy,
  data-residency, revocation, and hostile-file tests.

Add Teams-specific checks for invalid/missing bearer tokens, wrong
tenant/audience, oversized webhook body, valid activity ACK timing,
conversation-reference refresh, and absence of unintended Graph privileges.
See the pinned [OpenClaw Teams guide](https://docs.openclaw.ai/channels/msteams).

## Discord Gateway

Use numeric application/user/guild/channel snowflakes. Enable only the Message
Content intent required for this interaction; Presence, Server Members, Voice,
moderation, actions, agent components, native commands/approvals, thread
session spawning, and bot senders remain off.

Add Discord-specific checks for exact portal intents, one Gateway session,
disconnect/resume, thread/parent context without session spawning, and replay
of the same message ID across restart.

## Telegram long polling

Use one bot token/poller, positive numeric user IDs, and a negative `-100...`
supergroup ID. Usernames are not authorization. The group is allowlisted,
mention-gated, and passive ingestion is off. Webhooks, custom API roots,
private-network overrides, local-file roots, native commands/approvals,
reactions/actions, streaming/rich previews, topic changes, and session spawning
remain off.

Add Telegram-specific checks for `getMe`, exactly one poller, persisted update
offset, polling stall/recovery, media-group behavior, replay after a crash
between domain commit and offset completion, rate limiting, and token rotation.

## Meaning of a pass

G6 proves pinned plugins and static configuration schemas in a network-disabled
image. It does not prove a real channel.

A live channel passes only when every applicable common/provider row is `PASS`
with retained evidence, provider terms/permissions have been reviewed, and
rollback to `none` succeeds. Other channel families must remain empty.
