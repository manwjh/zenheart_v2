CREATE TABLE IF NOT EXISTS agent_space_relationships (
    id UUID PRIMARY KEY,
    agent_id VARCHAR(80) NOT NULL,
    target_agent_id VARCHAR(80) NOT NULL,
    relation_type VARCHAR(24) NOT NULL,
    visibility VARCHAR(20) NOT NULL DEFAULT 'private',
    note TEXT,
    source VARCHAR(24) NOT NULL DEFAULT 'agent',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_agent_space_relationships_agent_target UNIQUE (agent_id, target_agent_id)
);

CREATE INDEX IF NOT EXISTS ix_agent_space_relationships_agent_type
    ON agent_space_relationships (agent_id, relation_type);

CREATE INDEX IF NOT EXISTS ix_agent_space_relationships_target
    ON agent_space_relationships (target_agent_id);

CREATE TABLE IF NOT EXISTS agent_pinned_resources (
    id UUID PRIMARY KEY,
    agent_id VARCHAR(80) NOT NULL,
    resource_type VARCHAR(32) NOT NULL,
    resource_id VARCHAR(160) NOT NULL,
    relation_type VARCHAR(24) NOT NULL,
    visibility VARCHAR(20) NOT NULL DEFAULT 'private',
    title VARCHAR(200),
    url TEXT,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT uq_agent_pinned_resources_agent_resource_relation UNIQUE (
        agent_id,
        resource_type,
        resource_id,
        relation_type
    )
);

CREATE INDEX IF NOT EXISTS ix_agent_pinned_resources_agent_type
    ON agent_pinned_resources (agent_id, resource_type);

CREATE INDEX IF NOT EXISTS ix_agent_pinned_resources_agent_relation
    ON agent_pinned_resources (agent_id, relation_type);
