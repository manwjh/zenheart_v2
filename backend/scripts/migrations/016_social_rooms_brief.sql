-- Rename the room direction field from topic to brief.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'social_rooms'
      AND column_name = 'topic'
  )
  AND NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_name = 'social_rooms'
      AND column_name = 'brief'
  ) THEN
    ALTER TABLE social_rooms RENAME COLUMN topic TO brief;
  END IF;
END $$;
