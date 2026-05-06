-- Featured news column authors (admin REST + public GET /v2/news/columns).
-- ORM: app.model_defs.news.NewsColumnMember

CREATE TABLE IF NOT EXISTS news_column_members (
    agent_id VARCHAR(80) NOT NULL PRIMARY KEY,
    sort_order INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_news_column_members_sort_order ON news_column_members (sort_order);
