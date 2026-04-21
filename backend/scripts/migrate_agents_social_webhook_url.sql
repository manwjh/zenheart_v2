-- Optional HTTPS URL for A2A social event POSTs (see docs/social-websocket.md).
ALTER TABLE agents ADD COLUMN IF NOT EXISTS social_webhook_url TEXT;
