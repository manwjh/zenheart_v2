-- Add optional room-message reply reference for agent CAS/reply workflows.
BEGIN;

ALTER TABLE social_messages
  ADD COLUMN IF NOT EXISTS reply_to_message_id UUID NULL;

CREATE INDEX IF NOT EXISTS ix_social_messages_reply_to
  ON social_messages (reply_to_message_id);

COMMIT;
