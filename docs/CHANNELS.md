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

All profiles set `mediaMaxMb` from `VC_CHANNEL_MEDIA_MAX_MB`, a transport cap of 1–50 **MiB**. It is independent of, and should not exceed, the 25 MiB per-document limit the extraction lane enforces.
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

A destination group/channel ID is **required for every channel profile**, even
for a deployment that only intends to use direct messages: the validator
treats each provider's credential family as complete-or-empty, and the
customization profile's `approvals.allowed_channel_ids` must match it. If you
want DM-only operation, create one private channel, put the bot in it, use its
ID, and simply never post there — the channel lane stays mention-gated and
restricted to the same user allowlist.

## Common activation sequence

1. Keep `PRIMARY_CHANNEL=none`; pass offline, database, and exact-image gates.
2. Create the provider application/bot and record stable provider IDs.
3. Set `PRIMARY_CHANNEL` to the selected provider, fill only that credential/ID
   family and a reviewed comma-separated user list, and leave the other three
   families empty. Set `.env` mode `0600`.
4. Update the customization profile to match: `channels.selected` must equal the
   new `PRIMARY_CHANNEL` and `approvals.allowed_channel_ids` must exactly equal
   the destination IDs in `.env`, or every later lifecycle run fails closed on
   the profile/environment mismatch.
5. Validate `.env` and customization, render config, and record its SHA-256.
6. Build the exact image, then run the gateway's own checks. `openclaw` lives
   in the image, not on the host:

   ```sh
   compose() { docker compose -f docker-compose.yml -p openclaw-lead-research-v3 --env-file .env "$@"; }
   compose exec openclaw-gateway openclaw config validate
   compose exec openclaw-gateway openclaw doctor
   compose exec openclaw-gateway openclaw security audit
   compose exec openclaw-gateway openclaw channel status
   ```
7. Test each applicable matrix row below. Retain timestamps, config/image
   digests, redacted stable IDs, provider event IDs, database counts, and logs.
8. Resolve every warning. `FAIL`, `NOT RUN`, missing evidence, or an unexplained
   warning is not a channel pass.
9. Only then admit real messages.

Rollback is the same sequence in reverse, and the profile has to come with it:
set `PRIMARY_CHANNEL=none`, clear all channel families, set the profile's
`channels.selected` back to `none` and `approvals.allowed_channel_ids` to `[]`,
re-render, re-run `openclaw-state-init`, recreate the gateway, and prove no
connection exists. Clearing `.env` alone leaves the profile selecting a channel
and every later lifecycle run fails.

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
| CH-12 | Rollback to `none` | No active channel, credentials, binding, or callback exposure. The Compose file publishes the Teams webhook port on `MSTEAMS_WEBHOOK_HOST` (loopback by default) regardless of `PRIMARY_CHANNEL`; an open loopback socket with nothing serving it is expected here, an externally reachable one is not |

## Slack Socket Mode

Use one Slack app and one Socket Mode connection per gateway. Supply distinct
`xoxb-...` bot and `xapp-...` app tokens and grant only scopes/events required
by the pinned [OpenClaw Slack guide](https://docs.openclaw.ai/channels/slack).

Provider-side setup, in order:

1. Create an app at `api.slack.com/apps` in the target workspace.
2. Enable **Socket Mode**, and mint an app-level token with the
   `connections:write` scope — that is `SLACK_APP_TOKEN` (`xapp-…`).
3. Under OAuth & Permissions add the bot scopes the guide lists for
   messaging plus `files:read` for document intake, then install the app to
   the workspace. The resulting bot token is `SLACK_BOT_TOKEN` (`xoxb-…`).
4. Subscribe to the message and file events the guide lists; a text-only
   manifest validates but cannot commission CH-07.
5. Invite the bot to the destination channel.

Obtaining the IDs: enable Settings → Advanced → *Show member IDs* in the
Slack client, then copy a user's ID from their profile's overflow menu
(`U…`/`W…`) and the channel's ID from the channel details footer
(`C…`/`G…`). Display names are never authorization.

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

Four different identifiers are involved and they are easy to confuse:

- `MSTEAMS_APP_ID` / `MSTEAMS_TENANT_ID` — Entra application (client) and
  directory (tenant) **UUIDs**, from the app registration overview.
- `MSTEAMS_ALLOWED_USER_IDS` — each sender's Entra object **UUID**.
- `MSTEAMS_ALLOWED_TEAM_ID` and `MSTEAMS_ALLOWED_CHANNEL_ID` — Teams
  **conversation** IDs of the form `19:…@thread.tacv2`, *not* the team's
  Entra group UUID that the variable name suggests. Take them from the
  channel's *Get link to channel* URL (the `threadId` parameter) or from a
  received activity's `conversation.id`.
- `MSTEAMS_PUBLIC_WEBHOOK_URL` — the public HTTPS URL your reverse proxy
  serves, ending in `/api/messages`. Register exactly this URL as the bot
  resource's messaging endpoint, and install the Teams app package into the
  tenant, or no activity ever reaches the gateway.

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

Provider-side setup, in order:

1. Create an application at `discord.com/developers/applications`; its ID is
   `DISCORD_APPLICATION_ID`.
2. Add a Bot and copy its token into `DISCORD_BOT_TOKEN`.
3. Under Bot → Privileged Gateway Intents enable **Message Content** only.
4. Generate an OAuth2 URL (scopes `bot` plus `applications.commands` if you
   use them) and use it to invite the bot to the guild. Without this step the
   bot is never in the guild and no matrix row can pass.

Obtaining the IDs: enable *Advanced → Developer Mode* in the Discord client,
then right-click a user, the server, or the channel and choose *Copy ID* for
`DISCORD_ALLOWED_USER_IDS`, `DISCORD_ALLOWED_GUILD_ID` and
`DISCORD_ALLOWED_CHANNEL_ID`. All are numeric snowflakes.

Enable only the Message
Content intent required for this interaction; Presence, Server Members, Voice,
moderation, actions, agent components, native commands/approvals, thread
session spawning, and bot senders remain off.

Add Discord-specific checks for exact portal intents, one Gateway session,
disconnect/resume, thread/parent context without session spawning, and replay
of the same message ID across restart.

## Telegram long polling

Provider-side setup: message `@BotFather` in Telegram, `/newbot`, and copy the
issued token into `TELEGRAM_BOT_TOKEN`. Then `/setprivacy` → *Enable* so the
bot only receives messages addressed to it, and add the bot to the group.

Obtaining the IDs: a user's numeric ID and a supergroup's `-100…` ID are not
shown in the Telegram UI. Read them from the bot's own update stream after
sending it one message from the account and one in the group:
`curl -s "https://api.telegram.org/bot<token>/getUpdates"`, then take
`message.from.id` for `TELEGRAM_ALLOWED_USER_IDS` and `message.chat.id` for
`TELEGRAM_ALLOWED_GROUP_ID`. Run that only from the deployment host and do
not paste the token elsewhere.

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
