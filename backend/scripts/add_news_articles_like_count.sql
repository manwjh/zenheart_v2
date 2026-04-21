-- Add like_count column to news_articles.
-- Safe to run multiple times (IF NOT EXISTS).
ALTER TABLE news_articles
    ADD COLUMN IF NOT EXISTS like_count INTEGER NOT NULL DEFAULT 0;
