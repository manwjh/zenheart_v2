-- Run once against existing DBs (new installs get column from model + create_all on fresh tables only).
ALTER TABLE news_articles
  ADD COLUMN IF NOT EXISTS keywords jsonb NOT NULL DEFAULT '[]'::jsonb;
