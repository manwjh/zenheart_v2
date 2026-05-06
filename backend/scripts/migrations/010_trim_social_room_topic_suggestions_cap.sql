-- Cap social_room_topic_suggestions at 10 rows per room_id (keep newest by created_at, id).
-- Run once when upgrading environments that may have accumulated more than 10 pending rows.
-- PostgreSQL.

DELETE FROM social_room_topic_suggestions AS d
WHERE d.id IN (
  SELECT id FROM (
    SELECT id,
           ROW_NUMBER() OVER (
             PARTITION BY room_id
             ORDER BY created_at DESC, id DESC
           ) AS rn
    FROM social_room_topic_suggestions
  ) sub
  WHERE sub.rn > 10
);
