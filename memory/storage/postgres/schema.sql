CREATE TABLE IF NOT EXISTS memory_records (
  id TEXT PRIMARY KEY,
  memory_type TEXT NOT NULL CHECK (
    memory_type IN (
      'event',
      'description',
      'entity',
      'property',
      'link',
      'time_ref',
      'time_link',
      'summary'
    )
  ),
  text TEXT NOT NULL DEFAULT '',
  user_id TEXT,
  session_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memory_source_refs (
  id BIGSERIAL PRIMARY KEY,
  memory_record_id TEXT NOT NULL REFERENCES memory_records(id) ON DELETE CASCADE,
  position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  quote TEXT,
  span_start INTEGER,
  span_end INTEGER,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (memory_record_id, position)
);

CREATE INDEX IF NOT EXISTS idx_memory_records_scope
  ON memory_records(user_id, session_id, memory_type);

CREATE INDEX IF NOT EXISTS idx_memory_records_type
  ON memory_records(memory_type);

CREATE INDEX IF NOT EXISTS idx_memory_records_updated_at
  ON memory_records(updated_at DESC);

ALTER TABLE memory_records ADD COLUMN IF NOT EXISTS created_turn_id TEXT;
ALTER TABLE memory_records ADD COLUMN IF NOT EXISTS created_checkpoint_id TEXT;
ALTER TABLE memory_records ADD COLUMN IF NOT EXISTS created_checkpoint_sequence INTEGER;

CREATE INDEX IF NOT EXISTS idx_memory_records_checkpoint
  ON memory_records(session_id, created_checkpoint_sequence);

CREATE INDEX IF NOT EXISTS idx_memory_source_refs_memory_record_id
  ON memory_source_refs(memory_record_id);

CREATE INDEX IF NOT EXISTS idx_memory_source_refs_source
  ON memory_source_refs(source_type, source_id);
