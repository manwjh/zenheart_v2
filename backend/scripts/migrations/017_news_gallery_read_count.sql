-- Add read_count columns to public NEWS and Gallery content.
-- Safe to run multiple times (IF NOT EXISTS).
ALTER TABLE news_articles
    ADD COLUMN IF NOT EXISTS read_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE agent_gallery_works
    ADD COLUMN IF NOT EXISTS read_count INTEGER NOT NULL DEFAULT 0;
