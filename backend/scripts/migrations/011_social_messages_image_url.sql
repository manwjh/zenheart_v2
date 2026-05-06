-- Add optional image URL on social room messages.
BEGIN;

ALTER TABLE social_messages
  ADD COLUMN IF NOT EXISTS image_url TEXT NULL;

COMMIT;
