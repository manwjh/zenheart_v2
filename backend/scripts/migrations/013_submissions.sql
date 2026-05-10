CREATE TABLE IF NOT EXISTS submissions (
    id uuid PRIMARY KEY,
    kind varchar(20) NOT NULL,
    status varchar(30) NOT NULL DEFAULT 'pending',
    source varchar(60) NOT NULL,
    artifact_type varchar(40) NULL,
    title varchar(200) NOT NULL,
    body text NOT NULL,
    target_slug varchar(120) NULL,
    target_path text NULL,
    submitter_type varchar(20) NOT NULL,
    submitter_agent_id varchar(80) NULL,
    submitter_name varchar(120) NULL,
    submitter_contact varchar(320) NULL,
    reviewer_agent_id varchar(80) NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    report jsonb NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    reviewed_at timestamptz NULL,
    published_at timestamptz NULL,
    CONSTRAINT ck_submissions_kind CHECK (kind IN ('issue', 'proposal')),
    CONSTRAINT ck_submissions_status CHECK (
        status IN ('pending', 'claimed', 'changes_requested', 'accepted', 'rejected', 'published')
    ),
    CONSTRAINT ck_submissions_submitter_type CHECK (
        submitter_type IN ('anonymous', 'human', 'agent', 'system')
    )
);

CREATE INDEX IF NOT EXISTS ix_submissions_status_created
    ON submissions (status, created_at);

CREATE INDEX IF NOT EXISTS ix_submissions_kind_status
    ON submissions (kind, status);

CREATE INDEX IF NOT EXISTS ix_submissions_submitter_agent
    ON submissions (submitter_agent_id, created_at);

CREATE INDEX IF NOT EXISTS ix_submissions_submitter_agent_id
    ON submissions (submitter_agent_id);

CREATE INDEX IF NOT EXISTS ix_submissions_reviewer_agent_id
    ON submissions (reviewer_agent_id);

CREATE INDEX IF NOT EXISTS ix_submissions_target_slug
    ON submissions (target_slug);

CREATE TABLE IF NOT EXISTS submission_comments (
    id uuid PRIMARY KEY,
    submission_id uuid NOT NULL,
    author_type varchar(20) NOT NULL,
    author_agent_id varchar(80) NULL,
    author_name varchar(120) NULL,
    visibility varchar(20) NOT NULL DEFAULT 'public',
    body text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_submission_comments_submission_created
    ON submission_comments (submission_id, created_at);

CREATE INDEX IF NOT EXISTS ix_submission_comments_submission_id
    ON submission_comments (submission_id);

CREATE TABLE IF NOT EXISTS submission_reviews (
    id uuid PRIMARY KEY,
    submission_id uuid NOT NULL,
    reviewer_agent_id varchar(80) NOT NULL,
    decision varchar(30) NOT NULL,
    summary text NOT NULL,
    owner_report text NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_submission_reviews_submission_created
    ON submission_reviews (submission_id, created_at);

CREATE INDEX IF NOT EXISTS ix_submission_reviews_submission_id
    ON submission_reviews (submission_id);

CREATE INDEX IF NOT EXISTS ix_submission_reviews_reviewer_agent_id
    ON submission_reviews (reviewer_agent_id);

INSERT INTO level_permissions (module, action, max_level, description, updated_at)
VALUES
    ('submissions', 'submit', 9, 'All agents can create review submissions', now()),
    ('submissions', 'comment_own', 9, 'All agents can comment on their own submissions', now()),
    ('submissions', 'admin_review', 0, 'Only sovereign agents can review submissions', now())
ON CONFLICT (module, action) DO NOTHING;
