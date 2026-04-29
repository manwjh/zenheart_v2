-- Visitor topic suggestions for social rooms (not part of A2A chat transcript).
-- Room creator pulls and consumes via WebSocket pull_room_topics.

CREATE TABLE IF NOT EXISTS social_room_topic_suggestions (
    id         UUID         PRIMARY KEY,
    room_id    VARCHAR(36)  NOT NULL REFERENCES social_rooms(room_id) ON DELETE CASCADE,
    text       TEXT         NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS ix_social_room_topic_suggestions_room_created
  ON social_room_topic_suggestions (room_id, created_at);
