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

The four `config/channel-*.json5` overlays carry a `.json5` extension for
editor highlighting only: the renderer and the contract tests both parse them
with a **strict JSON** parser that rejects duplicate keys, so comments and
trailing commas are not accepted. An overlay edit that adds one fails closed at
`render_channel_config.py` with the offending line and column, before anything
reaches the gateway.

`scripts/render_channel_config.py` deep-merges only the selected strict overlay,
materializes list and destination sentinels, applies the configured model and
search providers, and writes `config/runtime/openclaw.json` atomically with
mode `0600`. A networkless initializer validates and copies that document to a
node-owned mode-`0400` named-volume file. Gateway and CLI mount it read-only.
Never edit the generated file; edit reviewed input, validate, render, re-run the
`openclaw-state-init` one-shot, and only then force-recreate the gateway. The
initializer is the sole writer of the volume the gateway mounts, so a render
followed by a gateway recreate alone leaves the previous config in place.

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

**One message authorizes at most ten documents.** The extension signs up to ten
media paths per turn (`MAX_MEDIA_PATHS` in
`runtime-extensions/vc-trusted-context/index.js`); an eleventh supported
document attached to the same message is inspected for its suffix but is not
included in the capability, so `document-ingest` refuses it as out of scope.
That refusal is deterministic and correct; what the chief says about it is model
wording, and normally reads as an unexplained request to re-attach one file.
Split a larger set across messages, or use the host-operator `/inbox` lane,
which has no such cap.

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

## Destination IDs and the reviewed profile

A destination group/channel ID is **required for every channel profile**, even
for a deployment that only intends to use direct messages: the validator
treats each provider's credential family as complete-or-empty, and the
customization profile's `approvals.allowed_channel_ids` must match it. If you
want DM-only operation, create one private channel, put the bot in it, use its
ID, and simply never post there — the channel lane stays mention-gated and
restricted to the same user allowlist.

`approvals.allowed_channel_ids` is a one-element list holding exactly the
*conversation* ID of the selected profile — **not** every ID in that credential
family:

| `channels.selected` | `approvals.allowed_channel_ids` must equal |
| --- | --- |
| `none` | `[]` |
| `slack` | `[SLACK_ALLOWED_CHANNEL_ID]` |
| `msteams` | `[MSTEAMS_ALLOWED_CHANNEL_ID]` — the channel, not `MSTEAMS_ALLOWED_TEAM_ID` |
| `discord` | `[DISCORD_ALLOWED_CHANNEL_ID]` — the channel, not `DISCORD_ALLOWED_GUILD_ID` |
| `telegram` | `[TELEGRAM_ALLOWED_GROUP_ID]` |

`MSTEAMS_ALLOWED_TEAM_ID` and `DISCORD_ALLOWED_GUILD_ID` are still required in
`.env` — they scope the containing team/guild — but they are containers rather
than destinations, so listing them here fails `check_customization.py`. The
error names the exact list it expected, so a wrong guess is one edit away from
correct.

## Common activation sequence

1. Keep `PRIMARY_CHANNEL=none`; pass offline, database, and exact-image gates.
2. Create the provider application/bot and record stable provider IDs.
3. Set `PRIMARY_CHANNEL` to the selected provider, fill only that credential/ID
   family and a reviewed comma-separated user list, and leave the other three
   families empty. Set `.env` mode `0600`.
4. Update the customization profile to match: `channels.selected` must equal the
   new `PRIMARY_CHANNEL` and `approvals.allowed_channel_ids` must exactly equal
   the one destination ID named in the table above, or every later lifecycle run
   fails closed on the profile/environment mismatch.
5. Validate `.env` and customization, render config, and record its SHA-256.
6. Build the exact image, then **deliver the rendered config and recreate the
   gateway**. The gateway reads its config from the runtime-config volume and
   the one-shot `openclaw-state-init` service is that volume's only writer, so
   recreating the gateway without it keeps the previous channel config mounted
   and every check in step 7 would measure the old configuration:

   ```sh
   compose() { docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env "$@"; }
   compose run --rm --no-deps openclaw-state-init
   compose up -d --wait --force-recreate --no-deps openclaw-gateway
   ```

   Re-running `./scripts/bootstrap.sh` does the same thing. `docs/RUNBOOK.md` §6
   carries the same sequence with the surrounding validation steps.
7. Run the gateway's own checks. `openclaw` lives in the image, not on the host:

   ```sh
   compose exec openclaw-gateway openclaw config validate
   compose exec openclaw-gateway openclaw doctor
   compose exec openclaw-gateway openclaw security audit
   compose exec openclaw-gateway openclaw channels status
   ```

   Every one of the four exits `0` on every profile. They still emit findings,
   and `docs/RUNBOOK.md` §5.1 carries the complete expected set with a
   disposition for each — read it before step 9, because two of those findings
   are channel-dependent and look like deviations otherwise:

   - `openclaw doctor` adds a `Doctor warnings` block about `vc-chief` lacking
     the `message` tool on *any* selected channel;
   - `openclaw security audit` adds `security.trust_model.multi_user_heuristic`
     on `slack`, `discord`, and `telegram` — but not on `msteams` — which adds
     **one warning** to whichever baseline applies.

   Both are expected, both restate reviewed design decisions, and **none of
   their suggested remedies may be applied.**

   Compare against the totals for the form you actually ran, because the two
   forms of the audit do not report the same count. `gateway.probe_failed` is a
   **`--deep`-only** check, so the plain `security audit` above reports one
   warning fewer than the `--deep` baselines RUNBOOK §5.1 tabulates. Measured on
   this release, on a live deployment and again inside the exact built image:

   | Command | `none`, `msteams` | `slack`, `discord`, `telegram` |
   | --- | --- | --- |
   | `openclaw security audit` (this step) | 0 critical · **1** warn · 1 info | 0 critical · **2** warn · 1 info |
   | `openclaw security audit --deep` (RUNBOOK §5.1) | 0 critical · **2** warn · 1 info | 0 critical · **3** warn · 1 info |

   An Ollama-mode or other small-model deployment adds `models.small_params` as
   a CRITICAL to whichever cell applies; RUNBOOK §5.1 carries its disposition.
8. Test each applicable matrix row below. Retain timestamps, config/image
   digests, redacted stable IDs, provider event IDs, database counts, and logs.
9. Resolve every warning. `FAIL`, `NOT RUN`, missing evidence, or an unexplained
   warning is not a channel pass. "Unexplained" means absent from RUNBOOK §5.1's
   expected set: a finding listed there with its disposition recorded *is*
   resolved for the purposes of this step.
10. Only then admit real messages.

Rollback is the same sequence in reverse, and the profile has to come with it:
set `PRIMARY_CHANNEL=none`, clear all channel families, set the profile's
`channels.selected` back to `none` and `approvals.allowed_channel_ids` to `[]`,
re-render, re-run `openclaw-state-init`, recreate the gateway, and prove no
connection exists. Clearing `.env` alone leaves the profile selecting a channel
and every later lifecycle run fails.

## Common live matrix

| ID | Test | Required result |
| --- | --- | --- |
| CH-01 | Exact plugin/image/config inspection, plus the credential probe `openclaw channels status --probe` (the plain `channels status` in step 7 defaults `--probe` to false) and, on Discord, the channel permission audit `openclaw channels capabilities --channel discord --target channel:<id>` — the pinned CLI restricts `--target` to Discord | Pinned plugin loads; no auth/schema/policy warning |
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

Provider-side setup, following the pinned guide:

1. At [api.slack.com/apps](https://api.slack.com/apps/new) choose **Create New
   App → From a manifest**, select the workspace, and paste the **Recommended**
   manifest from the pinned guide — the guide shows a Minimal alternative
   beside it that drops the file (`files:read`/`files:write`), reaction, pin,
   `mpim:*`, `emoji:read`, and `usergroups:read` scopes. The Recommended
   manifest carries the bot scopes and event subscriptions this integration
   expects, including `files:read` and the `message.*` events; a Minimal or
   hand-built text-only app validates but cannot commission CH-07.
2. Toggle **Socket Mode** on.
3. Under **Basic Information → App-Level Tokens** create a token with the
   `connections:write` scope. That is `SLACK_APP_TOKEN` (`xapp-…`).
4. **Install App → Install to Workspace**, then copy the **Bot User OAuth
   Token**. That is `SLACK_BOT_TOKEN` (`xoxb-…`).
5. Invite the bot to the destination channel.

Obtaining the IDs: right-click the channel → **Copy link**; the trailing `C…`
segment of that URL is `SLACK_ALLOWED_CHANNEL_ID`. User IDs (`U…`/`W…`) for
`SLACK_ALLOWED_USER_IDS` come from a member's profile or an API response.
Display names are never authorization.

Inbound document use requires the Slack app's file-read capability (including
`files:read`) and the corresponding reviewed file/message events; a minimal
text-only Slack manifest will validate but cannot commission CH-07. The
Recommended manifest also grants `files:write`, which the pinned plugin uses
only on its outbound attachment path; this deployment replies in text and never
exercises it. A deployment whose policy forbids an unused write scope deletes
the `"files:write",` line from the manifest before pasting it, and accepts that
outbound file sending would then fail at send time. Do not grant write scopes
beyond the Recommended manifest.

DMs are allowlisted. The selected channel is allowlisted, mention-gated, and
restricted to the same user list. Bot senders, name matching, native commands,
channel actions, unfurls, and native exec approvals are disabled. Thread
replies require an explicit mention. Slack-hosted files are best-effort;
thread-starter hydration may fail, in which case the user must attach the file
to the current request.

The overlay also sets `channels.slack.contextVisibility: "allowlist"`, matching
the Discord, Teams, and Telegram overlays. It covers the *supplemental thread
context* the plugin fetches from the Slack API around a thread reply — the
thread starter and the thread replies loaded up to `thread.initialHistoryLimit`
(unset here, so the plugin's own default of 20 applies) — and drops the ones
whose author is not in `SLACK_ALLOWED_USER_IDS`, which this overlay uses for
both the channel `users` list and the DM `allowFrom` list. One class of author
is exempt: the pinned plugin's `isSlackThreadContextSenderAllowed` returns
allowed for any message carrying a `bot_id`, without comparing it to the
allowlist, so a thread starter or reply posted by another Slack app or an
incoming webhook is injected regardless of `SLACK_ALLOWED_USER_IDS`. The
overlay's `allowBots: false` only stops such a message *triggering* a turn; it
does not govern what the thread-context builder injects. Treat other apps
posting in an allowlisted channel as context contributors. Without the key the
pinned plugin resolves the mode to `all` and passes that thread context through
unfiltered. Note the boundary: the key does not reach the pending room-history
window (`messages.groupChat.historyLimit`, unset here, harness default 50),
which a shared history helper assembles with no visibility mode of its own.
Because the thread starter now goes through the allowlist, re-run CH-05 and
CH-07 after re-rendering the config, and include a thread reply posted by a
second Slack app in the CH-05 matrix so the exemption above stays a measured
fact rather than a claim.

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
  **conversation** IDs of the form `19:…@thread.tacv2`, *not* the team's Entra
  group UUID that the variable name suggests. The pinned guide calls this the
  common mistake: take them from the **path** of the Teams link (the segment
  after `/team/` or `/channel/`, URL-decoded from `19%3A…%40thread.tacv2`), and
  **ignore the `groupId` query parameter** — that one is the Entra group ID.
  Older tenants may show `@thread.skype`, which this package also accepts.

Azure-side setup, following the pinned guide: create an **Azure Bot** resource
with **Type of App = Single Tenant** (multi-tenant registration was deprecated
after 2025-07-31); take the Microsoft App ID from its Configuration blade as
`MSTEAMS_APP_ID`; mint a client secret through Configuration → Manage Password →
Certificates & secrets and copy its **Value** as `MSTEAMS_APP_PASSWORD`; take
Directory (tenant) ID from Overview as `MSTEAMS_TENANT_ID`; set the messaging
endpoint to your public `/api/messages` URL; and finally enable **Channels →
Microsoft Teams → Configure → Save**, without which no activity is delivered.

Then build and sideload the Teams app package, per the same guide. Its
`manifest.json` must set `bots[].botId` and `webApplicationInfo.id` to
`MSTEAMS_APP_ID`; `bots[].scopes` to `personal`, `team`, and `groupChat`;
`bots[].supportsFiles: true`, without which the direct-message attachment lane
this package commissions as CH-07 cannot work; and
`authorization.permissions.resourceSpecific` channel read/send, without which
the mention-gated team/channel lane in CH-05 receives nothing.

- `MSTEAMS_PUBLIC_WEBHOOK_URL` — the public HTTPS URL your reverse proxy
  serves, ending in `/api/messages`. Register exactly this URL as the bot
  resource's messaging endpoint, and install the Teams app package into the
  tenant, or no activity ever reaches the gateway. Record the **proxy's**
  address here, not the loopback callback described at the top of this section:
  the path is identical on both, which is what makes this field easy to get
  wrong. Nothing reads the value at runtime, so `scripts/check_env.sh` is what
  catches a mis-recorded one. It refuses a loopback, private, link-local,
  carrier-NAT, documentation, reserved, unspecified, or multicast IPv4 or IPv6
  literal **written in canonical form**, and refuses `localhost`, any
  `.localhost` or `.local` name, and any single-label name — the last of which is
  also what rejects the dotless integer and hexadecimal spellings, `2130706433`
  and `0x7f000001`.

  Canonical form is what `ipaddress.ip_address` accepts, and it is stricter than
  what resolvers accept. Since CPython 3.9.5 (CVE-2021-29921) `ipaddress` rejects
  a leading zero in any octet, and it has never accepted abbreviated, hex or
  octal octets — so **every non-canonical spelling falls through to the DNS-name
  branch and is accepted**, including four-octet ones. Measured against the
  shipped validator: `127.1`, `10.1`, `192.168.1`, `172.16.1`, `0x7f.1`,
  `0177.1`, and also the fully written `127.000.000.001`, `127.0.0.01`,
  `0177.0.0.1`, `0x7f.0.0.1`, `192.168.000.001` and `010.0.0.1` are all accepted
  — while `inet_aton`, and therefore curl and anything else resolving through it,
  expands them to loopback or RFC1918 addresses (`010.0.0.1` becomes `8.0.0.1`,
  which is neither). A syntactically public name is accepted without a lookup
  either way, so CH-01 stays the step that confirms the URL actually reaches your
  proxy.

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

Provider-side setup, following the pinned
[OpenClaw Discord guide](https://docs.openclaw.ai/channels/discord):

1. At the [Discord Developer Portal](https://discord.com/developers/applications)
   choose **New Application**; its ID is `DISCORD_APPLICATION_ID`.
2. Open **Bot**, then **Reset Token** and copy the value into
   `DISCORD_BOT_TOKEN`. Discord shows a bot token only once, so an existing
   application needs a reset rather than a lookup.
3. Under **Bot → Privileged Gateway Intents** enable **Message Content** only.
   The guide also suggests Server Members and Presence; this deployment
   deliberately leaves both off, which costs role allowlists and
   name-to-ID matching that it does not use.
4. Under **OAuth2 → URL Generator** select scopes `bot` and
   `applications.commands`, and bot permissions View Channels, Send Messages,
   Read Message History, Embed Links and Attach Files (add Send Messages in
   Threads for thread use). Open the generated URL to invite the bot to the
   guild. Without this step the bot is never in the guild and no matrix row can
   pass.

Obtaining the IDs: enable **User Settings → Developer → Developer Mode** (on
mobile, App Settings → Advanced), then right-click the server icon → *Copy
Server ID*, an avatar → *Copy User ID*, and a channel → *Copy Channel ID* for
`DISCORD_ALLOWED_GUILD_ID`, `DISCORD_ALLOWED_USER_IDS` and
`DISCORD_ALLOWED_CHANNEL_ID`. All are numeric snowflakes.

Enable only the Message
Content intent required for this interaction; Presence, Server Members, Voice,
moderation, actions, agent components, native commands/approvals, thread
session spawning, and bot senders remain off.

Add Discord-specific checks for exact portal intents, one Gateway session,
disconnect/resume, thread/parent context without session spawning, and replay
of the same message ID across restart.

## Telegram long polling

Provider-side setup, following the pinned
[OpenClaw Telegram guide](https://docs.openclaw.ai/channels/telegram): message
`@BotFather`, run `/newbot`, and copy the issued token into
`TELEGRAM_BOT_TOKEN`. Add the bot to the group. Leave privacy mode at its
default **enabled** so the bot only receives messages addressed to it — that
matches this deployment's mention-gated group lane. If you ever change the
setting with `/setprivacy`, **remove and re-add the bot in every group**, or the
change does not take effect there.

Obtaining the IDs: a user's numeric ID and a supergroup's `-100…` ID are not
shown in the Telegram UI. Collect them **before** you select the channel: both
values must already be in `.env` for `check_env.sh` to accept a Telegram
profile, so the gateway is never connected to Telegram while they are still
unknown, and its log cannot be the source. Send the bot one direct message and
post one message in the group that @-mentions the bot — with privacy mode at
its default enabled, only messages addressed to the bot (mentions, `/commands`,
replies to it) reach it, so a plain group message never appears in
`getUpdates`. Then ask Telegram directly, on the deployment host only:

```sh
curl -s "https://api.telegram.org/bot<token>/getUpdates"
```

Take `result[].message.from.id` for `TELEGRAM_ALLOWED_USER_IDS` and
`result[].message.chat.id` for `TELEGRAM_ALLOWED_GROUP_ID`. Once the channel is
running, the same fields also appear in the gateway log, which is the easier
route when you later add a user:

```sh
docker compose -f docker-compose.yml -p vc-lead-research-v3 --env-file .env \
  logs -f openclaw-gateway
```

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
