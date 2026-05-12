-- Room door control for owner-managed join gating.

ALTER TABLE social_rooms
  ADD COLUMN IF NOT EXISTS door_closed BOOLEAN NOT NULL DEFAULT FALSE;
