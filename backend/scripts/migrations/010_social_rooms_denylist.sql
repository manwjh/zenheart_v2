-- Private room denylist support.
-- Adds denylist_agent_ids to social_rooms for blocked agent_id sets.

ALTER TABLE social_rooms
  ADD COLUMN IF NOT EXISTS denylist_agent_ids JSONB;
