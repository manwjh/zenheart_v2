-- Optional copy of token for self-service credential resend (no rotation).
-- Production may already have this column; IF NOT EXISTS keeps the migration safe.
ALTER TABLE agents ADD COLUMN IF NOT EXISTS token_plaintext TEXT;
