-- Sync agents.apply_reason when the ORM model has the column but the database was created earlier without it.
-- PostgreSQL 11+ (IF NOT EXISTS on ADD COLUMN).
ALTER TABLE agents ADD COLUMN IF NOT EXISTS apply_reason TEXT;
