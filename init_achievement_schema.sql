CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS repositories (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL UNIQUE,
  local_path TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS commits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  commit_hash TEXT NOT NULL,
  commit_date TIMESTAMPTZ NOT NULL,
  commit_message TEXT NOT NULL,
  raw_files JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (repository_id, commit_hash)
);

CREATE TABLE IF NOT EXISTS commit_achievements (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  commit_id UUID NOT NULL REFERENCES commits(id) ON DELETE CASCADE,
  ai_bullet TEXT NOT NULL,
  model_name TEXT NOT NULL,
  model_version TEXT,
  token_usage INTEGER,
  payload_checksum TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  processing_status TEXT NOT NULL DEFAULT 'completed',
  processed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (commit_id, payload_checksum)
);

CREATE TABLE IF NOT EXISTS repository_summaries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  repository_id UUID NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
  start_date DATE NOT NULL,
  end_date DATE NOT NULL,
  summary_text TEXT NOT NULL,
  commit_count INTEGER NOT NULL,
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (repository_id, start_date, end_date),
  CHECK (start_date <= end_date)
);

CREATE TABLE IF NOT EXISTS summary_commit_map (
  summary_id UUID NOT NULL REFERENCES repository_summaries(id) ON DELETE CASCADE,
  commit_id UUID NOT NULL REFERENCES commits(id) ON DELETE CASCADE,
  PRIMARY KEY (summary_id, commit_id)
);

CREATE INDEX IF NOT EXISTS idx_commits_repository_id ON commits (repository_id);
CREATE INDEX IF NOT EXISTS idx_commits_commit_date ON commits (commit_date);
CREATE INDEX IF NOT EXISTS idx_commits_repository_id_commit_date ON commits (repository_id, commit_date);

CREATE INDEX IF NOT EXISTS idx_commit_achievements_commit_id ON commit_achievements (commit_id);
CREATE INDEX IF NOT EXISTS idx_commit_achievements_checksum ON commit_achievements (payload_checksum);

CREATE INDEX IF NOT EXISTS idx_repository_summaries_repository_id ON repository_summaries (repository_id);
CREATE INDEX IF NOT EXISTS idx_repository_summaries_start_date ON repository_summaries (start_date);
CREATE INDEX IF NOT EXISTS idx_repository_summaries_end_date ON repository_summaries (end_date);

CREATE INDEX IF NOT EXISTS idx_summary_commit_map_commit_id ON summary_commit_map (commit_id);
