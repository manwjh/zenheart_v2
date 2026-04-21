-- Persistent chat message history for A2A social rooms.
CREATE TABLE IF NOT EXISTS social_messages (
    id         UUID         PRIMARY KEY,
    room_id    VARCHAR(36)  NOT NULL,
    agent_id   VARCHAR(80)  NOT NULL,
    agent_name VARCHAR(120) NOT NULL,
    text       TEXT         NOT NULL,
    mentions   JSONB,
    sent_at    TIMESTAMPTZ  NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_social_messages_room_id   ON social_messages (room_id);
CREATE INDEX IF NOT EXISTS ix_social_messages_room_sent ON social_messages (room_id, sent_at);
