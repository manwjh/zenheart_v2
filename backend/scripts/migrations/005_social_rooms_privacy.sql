-- Private invite-only rooms, content observability, and allow list (v2).
-- Run against PostgreSQL when upgrading an existing v2 database.

ALTER TABLE social_rooms ADD COLUMN IF NOT EXISTS is_private BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE social_rooms ADD COLUMN IF NOT EXISTS observable BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE social_rooms ADD COLUMN IF NOT EXISTS allowlist_agent_ids JSONB;
