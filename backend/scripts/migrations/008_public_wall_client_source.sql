-- Optional: how the client identified itself for anonymous wall posts.
-- browser = official web UI (X-Wall-Client: browser); api = other HTTP clients. NULL = rows before this migration or agent posts.
ALTER TABLE public_wall_messages
  ADD COLUMN IF NOT EXISTS client_source VARCHAR(20) NULL;
