-- Private rooms do not use idle TTL in storage (behavior is driven by is_private in app code).
-- Public rooms keep ttl_minutes (idle window at creation) and expires_at (first idle boundary snapshot).
-- Widen ttl_minutes for legacy SMALLINT deployments; then allow NULL on both columns.

ALTER TABLE social_rooms
  ALTER COLUMN ttl_minutes TYPE INTEGER USING ttl_minutes::integer;

ALTER TABLE social_rooms
  ALTER COLUMN ttl_minutes DROP NOT NULL;

ALTER TABLE social_rooms
  ALTER COLUMN expires_at DROP NOT NULL;

UPDATE social_rooms
SET ttl_minutes = NULL, expires_at = NULL
WHERE is_private = TRUE;
