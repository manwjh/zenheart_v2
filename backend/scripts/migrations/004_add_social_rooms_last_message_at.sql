-- Add last_message_at to social_rooms (was missing from the original schema).
ALTER TABLE social_rooms
    ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS ix_social_rooms_last_message
    ON social_rooms (last_message_at);
