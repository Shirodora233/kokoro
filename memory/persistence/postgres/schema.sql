CREATE TABLE IF NOT EXISTS memory_events (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  session_id TEXT,
  title TEXT NOT NULL,
  summary TEXT,
  event_type TEXT,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
  confidence TEXT NOT NULL DEFAULT 'medium'
    CHECK (confidence IN ('high', 'medium', 'low')),
  importance TEXT NOT NULL DEFAULT 'medium'
    CHECK (importance IN ('high', 'medium', 'low')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  merged_into_id TEXT REFERENCES memory_events(id) ON DELETE SET NULL,
  deleted_at TIMESTAMPTZ,
  deleted_reason TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_descriptions (
  id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES memory_events(id) ON DELETE CASCADE,
  user_id TEXT,
  session_id TEXT,
  content TEXT NOT NULL,
  description_type TEXT,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
  confidence TEXT NOT NULL DEFAULT 'medium'
    CHECK (confidence IN ('high', 'medium', 'low')),
  importance TEXT NOT NULL DEFAULT 'low'
    CHECK (importance IN ('high', 'medium', 'low')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  merged_into_id TEXT REFERENCES memory_descriptions(id) ON DELETE SET NULL,
  deleted_at TIMESTAMPTZ,
  deleted_reason TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_entities (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  session_id TEXT,
  scope TEXT NOT NULL DEFAULT 'session'
    CHECK (scope IN ('global', 'user', 'session')),
  name TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  identity_summary TEXT,
  aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
  confidence TEXT NOT NULL DEFAULT 'medium'
    CHECK (confidence IN ('high', 'medium', 'low')),
  importance TEXT NOT NULL DEFAULT 'medium'
    CHECK (importance IN ('high', 'medium', 'low')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_properties (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
  user_id TEXT,
  session_id TEXT,
  content TEXT NOT NULL,
  property_type TEXT,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
  confidence TEXT NOT NULL DEFAULT 'medium'
    CHECK (confidence IN ('high', 'medium', 'low')),
  importance TEXT NOT NULL DEFAULT 'medium'
    CHECK (importance IN ('high', 'medium', 'low')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  invalidated_by TEXT REFERENCES memory_properties(id) ON DELETE SET NULL,
  merged_into_id TEXT REFERENCES memory_properties(id) ON DELETE SET NULL,
  deleted_at TIMESTAMPTZ,
  deleted_reason TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_links (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  from_type TEXT NOT NULL
    CHECK (from_type IN ('event', 'description', 'entity', 'property', 'link', 'time_ref', 'time_link', 'message', 'message_section', 'summary')),
  from_id TEXT NOT NULL,
  to_type TEXT NOT NULL
    CHECK (to_type IN ('event', 'description', 'entity', 'property', 'link', 'time_ref', 'time_link', 'message', 'message_section', 'summary')),
  to_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
  confidence TEXT NOT NULL DEFAULT 'medium'
    CHECK (confidence IN ('high', 'medium', 'low')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  deleted_at TIMESTAMPTZ,
  deleted_reason TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (from_type, from_id, to_type, to_id, relation_type)
);

CREATE TABLE IF NOT EXISTS memory_time_refs (
  id TEXT PRIMARY KEY,
  raw_text TEXT NOT NULL,
  time_kind TEXT NOT NULL
    CHECK (time_kind IN ('exact', 'relative', 'vague', 'duration', 'recurring')),
  timeline_kind TEXT NOT NULL
    CHECK (timeline_kind IN ('real_world', 'fictional')),
  certainty TEXT NOT NULL
    CHECK (certainty IN ('resolved', 'inferred', 'vague', 'unknown')),
  anchor_timezone TEXT NOT NULL,
  anchor_utc_offset TEXT NOT NULL,
  anchor_message_id TEXT,
  resolved_start TEXT,
  resolved_end TEXT,
  granularity TEXT,
  description TEXT,
  duration_text TEXT,
  recurrence_text TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_time_links (
  id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL
    CHECK (target_type IN ('event', 'description', 'entity', 'property', 'link', 'time_ref', 'time_link', 'message', 'message_section', 'summary')),
  target_id TEXT NOT NULL,
  time_ref_id TEXT NOT NULL REFERENCES memory_time_refs(id) ON DELETE CASCADE,
  time_role TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'medium'
    CHECK (confidence IN ('high', 'medium', 'low')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  UNIQUE (target_type, target_id, time_ref_id, time_role)
);

CREATE TABLE IF NOT EXISTS memory_sources (
  id TEXT PRIMARY KEY,
  memory_type TEXT NOT NULL
    CHECK (memory_type IN ('event', 'description', 'entity', 'property', 'link', 'time_ref', 'time_link', 'message', 'message_section', 'summary')),
  memory_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  quote TEXT,
  span_start INTEGER,
  span_end INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_memory_events_scope
  ON memory_events(user_id, session_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_events_type
  ON memory_events(event_type, status);

CREATE INDEX IF NOT EXISTS idx_memory_descriptions_event
  ON memory_descriptions(event_id);
CREATE INDEX IF NOT EXISTS idx_memory_descriptions_scope
  ON memory_descriptions(user_id, session_id, status);

CREATE INDEX IF NOT EXISTS idx_memory_entities_scope
  ON memory_entities(scope, user_id, session_id);
CREATE INDEX IF NOT EXISTS idx_memory_entities_name
  ON memory_entities(name);

CREATE INDEX IF NOT EXISTS idx_memory_properties_entity
  ON memory_properties(entity_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_properties_scope
  ON memory_properties(user_id, session_id, status);

CREATE INDEX IF NOT EXISTS idx_memory_links_from
  ON memory_links(from_type, from_id);
CREATE INDEX IF NOT EXISTS idx_memory_links_to
  ON memory_links(to_type, to_id);

CREATE INDEX IF NOT EXISTS idx_memory_time_refs_kind
  ON memory_time_refs(timeline_kind, time_kind, certainty);
CREATE INDEX IF NOT EXISTS idx_memory_time_links_target
  ON memory_time_links(target_type, target_id, time_role);
CREATE INDEX IF NOT EXISTS idx_memory_time_links_time_ref
  ON memory_time_links(time_ref_id);

CREATE INDEX IF NOT EXISTS idx_memory_sources_memory
  ON memory_sources(memory_type, memory_id);
CREATE INDEX IF NOT EXISTS idx_memory_sources_source
  ON memory_sources(source_type, source_id);

ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS created_turn_id TEXT;
ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS created_checkpoint_id TEXT;
ALTER TABLE memory_events ADD COLUMN IF NOT EXISTS created_checkpoint_sequence INTEGER;
ALTER TABLE memory_descriptions ADD COLUMN IF NOT EXISTS created_turn_id TEXT;
ALTER TABLE memory_descriptions ADD COLUMN IF NOT EXISTS created_checkpoint_id TEXT;
ALTER TABLE memory_descriptions ADD COLUMN IF NOT EXISTS created_checkpoint_sequence INTEGER;
ALTER TABLE memory_entities ADD COLUMN IF NOT EXISTS created_turn_id TEXT;
ALTER TABLE memory_entities ADD COLUMN IF NOT EXISTS created_checkpoint_id TEXT;
ALTER TABLE memory_entities ADD COLUMN IF NOT EXISTS created_checkpoint_sequence INTEGER;
ALTER TABLE memory_properties ADD COLUMN IF NOT EXISTS created_turn_id TEXT;
ALTER TABLE memory_properties ADD COLUMN IF NOT EXISTS created_checkpoint_id TEXT;
ALTER TABLE memory_properties ADD COLUMN IF NOT EXISTS created_checkpoint_sequence INTEGER;
ALTER TABLE memory_links ADD COLUMN IF NOT EXISTS created_turn_id TEXT;
ALTER TABLE memory_links ADD COLUMN IF NOT EXISTS created_checkpoint_id TEXT;
ALTER TABLE memory_links ADD COLUMN IF NOT EXISTS created_checkpoint_sequence INTEGER;
ALTER TABLE memory_time_refs ADD COLUMN IF NOT EXISTS created_turn_id TEXT;
ALTER TABLE memory_time_refs ADD COLUMN IF NOT EXISTS created_checkpoint_id TEXT;
ALTER TABLE memory_time_refs ADD COLUMN IF NOT EXISTS created_checkpoint_sequence INTEGER;
ALTER TABLE memory_time_links ADD COLUMN IF NOT EXISTS created_turn_id TEXT;
ALTER TABLE memory_time_links ADD COLUMN IF NOT EXISTS created_checkpoint_id TEXT;
ALTER TABLE memory_time_links ADD COLUMN IF NOT EXISTS created_checkpoint_sequence INTEGER;

CREATE INDEX IF NOT EXISTS idx_memory_events_checkpoint
  ON memory_events(session_id, created_checkpoint_sequence, status);
CREATE INDEX IF NOT EXISTS idx_memory_descriptions_checkpoint
  ON memory_descriptions(session_id, created_checkpoint_sequence, status);
CREATE INDEX IF NOT EXISTS idx_memory_entities_checkpoint
  ON memory_entities(session_id, created_checkpoint_sequence);
CREATE INDEX IF NOT EXISTS idx_memory_properties_checkpoint
  ON memory_properties(session_id, created_checkpoint_sequence, status);
