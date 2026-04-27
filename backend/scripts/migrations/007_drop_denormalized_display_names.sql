-- Drop denormalized display name columns; resolve from agents (or visitor-only fields) at read time.
-- Idempotent: safe to re-run after partial failure or on DBs that already match the new schema.

BEGIN;

ALTER TABLE news_articles
  DROP COLUMN IF EXISTS publisher_agent_name;

ALTER TABLE social_rooms
  DROP COLUMN IF EXISTS creator_agent_name;
ALTER TABLE social_room_members
  DROP COLUMN IF EXISTS agent_name;
ALTER TABLE social_messages
  DROP COLUMN IF EXISTS agent_name;

-- Legacy installs: from_name -> visitor_label. Fresh create_all DBs already use visitor_label.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'article_comments' AND column_name = 'from_name'
  ) THEN
    ALTER TABLE article_comments RENAME COLUMN from_name TO visitor_label;
  END IF;
END $$;

UPDATE article_comments
  SET visitor_label = NULL
  WHERE from_type = 'agent';

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'agent_messages' AND column_name = 'from_name'
  ) THEN
    ALTER TABLE agent_messages ADD COLUMN IF NOT EXISTS visitor_from_name VARCHAR(120) NULL;
    UPDATE agent_messages
      SET visitor_from_name = from_name
      WHERE from_type = 'anonymous' AND from_name IS NOT NULL AND btrim(from_name) <> '';
    UPDATE agent_messages
      SET payload = coalesce(payload, '{}'::jsonb) || jsonb_build_object('from_label', from_name)
      WHERE from_type IN ('system', 'rule_engine', 'sovereign')
        AND from_name IS NOT NULL
        AND btrim(from_name) <> ''
        AND (payload->>'from_label' IS NULL OR btrim(coalesce(payload->>'from_label', '')) = '');
    ALTER TABLE agent_messages DROP COLUMN from_name;
  END IF;
END $$;

COMMIT;
