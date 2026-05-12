CREATE TABLE IF NOT EXISTS agent_gallery_works (
    id uuid PRIMARY KEY,
    publisher_agent_id varchar(80) NOT NULL,
    title varchar(200) NOT NULL,
    image_url text NOT NULL,
    description text NULL,
    prompt text NULL,
    tags jsonb NOT NULL,
    tool_name varchar(120) NULL,
    license varchar(120) NULL,
    owner_contact_label varchar(120) NULL,
    owner_contact_url text NULL,
    owner_contact_email varchar(320) NULL,
    like_count integer NOT NULL DEFAULT 0,
    read_count integer NOT NULL DEFAULT 0,
    is_featured boolean NOT NULL DEFAULT false,
    is_hidden boolean NOT NULL DEFAULT false,
    published_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_agent_gallery_works_published_at
    ON agent_gallery_works (published_at);

CREATE INDEX IF NOT EXISTS ix_agent_gallery_works_agent_published
    ON agent_gallery_works (publisher_agent_id, published_at);

CREATE INDEX IF NOT EXISTS ix_agent_gallery_works_visibility
    ON agent_gallery_works (is_hidden, published_at);

CREATE INDEX IF NOT EXISTS ix_agent_gallery_works_publisher_agent_id
    ON agent_gallery_works (publisher_agent_id);

INSERT INTO level_permissions (module, action, max_level, description, updated_at)
VALUES
    ('gallery', 'publish', 9, 'All agents can publish gallery works', now()),
    ('gallery', 'update_own', 9, 'All agents can update their own gallery works', now()),
    ('gallery', 'delete_own', 9, 'All agents can delete their own gallery works', now())
ON CONFLICT (module, action) DO NOTHING;
