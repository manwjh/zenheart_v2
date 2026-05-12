-- Optional HTTPS URL for A2A social event POSTs (see v2/docs/protocol/A05_social-protocol.md).
ALTER TABLE agents ADD COLUMN IF NOT EXISTS social_webhook_url TEXT;
