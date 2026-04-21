-- Social rooms v2: idle-based lifecycle (no TTL / max_members on room row).
-- Run against an existing DB that still has the old social_rooms columns.
-- For greenfield installs, `Base.metadata.create_all` matches the new model.

ALTER TABLE social_rooms ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS ix_social_rooms_last_message ON social_rooms (last_message_at);

-- Drop legacy columns (PostgreSQL 11+). Comment out if your version lacks IF EXISTS.
ALTER TABLE social_rooms DROP COLUMN IF EXISTS max_members;
ALTER TABLE social_rooms DROP COLUMN IF EXISTS ttl_minutes;
ALTER TABLE social_rooms DROP COLUMN IF EXISTS expires_at;
