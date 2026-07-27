-- SPDX-License-Identifier: 0BSD
-- OpenClaw Lead Research System 2.0
-- Expand the notification provider contract for the four channel profiles.

BEGIN;

SET LOCAL lock_timeout = '10s';
SET LOCAL statement_timeout = '30s';

ALTER TABLE notification_outbox
  DROP CONSTRAINT IF EXISTS notification_outbox_provider_check;

-- Provider ids match the configured channel ids everywhere else in the
-- system (channel_principals, the trusted-context plugin, config/): the
-- Microsoft Teams channel is 'msteams', never 'teams'.
ALTER TABLE notification_outbox
  ADD CONSTRAINT notification_outbox_provider_check
  CHECK (provider IN ('slack', 'msteams', 'discord', 'telegram', 'internal_log'));

COMMIT;
