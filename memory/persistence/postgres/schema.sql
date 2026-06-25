CREATE TABLE IF NOT EXISTS memory_objects (
  id TEXT PRIMARY KEY,
  object_type TEXT NOT NULL
    CHECK (object_type IN (
      'event', 'description', 'entity', 'property', 'relation',
      'time_ref', 'time_link', 'message', 'message_section', 'summary'
    )),
  user_id TEXT,
  session_id TEXT,
  scope TEXT NOT NULL DEFAULT 'session'
    CHECK (scope IN ('global', 'user', 'session')),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
  confidence TEXT NOT NULL DEFAULT 'medium'
    CHECK (confidence IN ('high', 'medium', 'low')),
  importance TEXT NOT NULL DEFAULT 'medium'
    CHECK (importance IN ('high', 'medium', 'low')),
  created_turn_id TEXT,
  created_checkpoint_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  merged_into_object_id TEXT REFERENCES memory_objects(id) ON DELETE SET NULL,
  deleted_at TIMESTAMPTZ,
  deleted_reason TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_events (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  summary TEXT,
  event_type TEXT
);

CREATE TABLE IF NOT EXISTS memory_descriptions (
  id TEXT PRIMARY KEY,
  event_id TEXT NOT NULL REFERENCES memory_events(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  description_type TEXT
);

CREATE TABLE IF NOT EXISTS memory_entities (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  identity_summary TEXT
);

CREATE TABLE IF NOT EXISTS memory_entity_aliases (
  entity_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
  alias TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (entity_id, alias)
);

CREATE TABLE IF NOT EXISTS memory_properties (
  id TEXT PRIMARY KEY,
  entity_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  property_type TEXT
);

CREATE TABLE IF NOT EXISTS memory_relations (
  id TEXT PRIMARY KEY,
  from_object_id TEXT NOT NULL REFERENCES memory_objects(id) ON DELETE CASCADE,
  to_object_id TEXT NOT NULL REFERENCES memory_objects(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL,
  reason TEXT,
  UNIQUE (from_object_id, to_object_id, relation_type)
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
  recurrence_text TEXT
);

CREATE TABLE IF NOT EXISTS memory_time_links (
  id TEXT PRIMARY KEY,
  target_object_id TEXT NOT NULL REFERENCES memory_objects(id) ON DELETE CASCADE,
  time_ref_object_id TEXT NOT NULL REFERENCES memory_time_refs(id) ON DELETE CASCADE,
  time_role TEXT NOT NULL,
  UNIQUE (target_object_id, time_ref_object_id, time_role)
);

CREATE TABLE IF NOT EXISTS memory_sources (
  id TEXT PRIMARY KEY,
  object_id TEXT NOT NULL REFERENCES memory_objects(id) ON DELETE CASCADE,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  quote TEXT,
  span_start INTEGER,
  span_end INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_revisions (
  revision_id TEXT PRIMARY KEY,
  object_id TEXT NOT NULL REFERENCES memory_objects(id) ON DELETE CASCADE,
  checkpoint_id TEXT,
  turn_id TEXT,
  operation TEXT NOT NULL
    CHECK (operation IN (
      'create', 'reuse', 'attach', 'update', 'merge', 'invalidate',
      'flag_conflict', 'ignore', 'seed'
    )),
  status_after TEXT NOT NULL DEFAULT 'active'
    CHECK (status_after IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
  confidence TEXT NOT NULL DEFAULT 'medium'
    CHECK (confidence IN ('high', 'medium', 'low')),
  importance TEXT NOT NULL DEFAULT 'medium'
    CHECK (importance IN ('high', 'medium', 'low')),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  previous_revision_id TEXT REFERENCES memory_revisions(revision_id) ON DELETE SET NULL,
  merged_into_object_id TEXT REFERENCES memory_objects(id) ON DELETE SET NULL,
  operation_index INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memory_events_object_fk'
  ) THEN
    ALTER TABLE memory_events
      ADD CONSTRAINT memory_events_object_fk
      FOREIGN KEY (id) REFERENCES memory_objects(id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memory_descriptions_object_fk'
  ) THEN
    ALTER TABLE memory_descriptions
      ADD CONSTRAINT memory_descriptions_object_fk
      FOREIGN KEY (id) REFERENCES memory_objects(id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memory_entities_object_fk'
  ) THEN
    ALTER TABLE memory_entities
      ADD CONSTRAINT memory_entities_object_fk
      FOREIGN KEY (id) REFERENCES memory_objects(id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memory_properties_object_fk'
  ) THEN
    ALTER TABLE memory_properties
      ADD CONSTRAINT memory_properties_object_fk
      FOREIGN KEY (id) REFERENCES memory_objects(id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memory_time_refs_object_fk'
  ) THEN
    ALTER TABLE memory_time_refs
      ADD CONSTRAINT memory_time_refs_object_fk
      FOREIGN KEY (id) REFERENCES memory_objects(id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memory_time_links_object_fk'
  ) THEN
    ALTER TABLE memory_time_links
      ADD CONSTRAINT memory_time_links_object_fk
      FOREIGN KEY (id) REFERENCES memory_objects(id) ON DELETE CASCADE;
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memory_relations_object_fk'
  ) THEN
    ALTER TABLE memory_relations
      ADD CONSTRAINT memory_relations_object_fk
      FOREIGN KEY (id) REFERENCES memory_objects(id) ON DELETE CASCADE;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_memory_objects_scope
  ON memory_objects(scope, user_id, session_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_objects_checkpoint
  ON memory_objects(session_id, created_checkpoint_id, status);
CREATE INDEX IF NOT EXISTS idx_memory_objects_type_updated
  ON memory_objects(object_type, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_memory_events_type
  ON memory_events(event_type);
CREATE INDEX IF NOT EXISTS idx_memory_descriptions_event
  ON memory_descriptions(event_id);
CREATE INDEX IF NOT EXISTS idx_memory_entities_name
  ON memory_entities(name);
CREATE INDEX IF NOT EXISTS idx_memory_entity_aliases_alias
  ON memory_entity_aliases(alias);
CREATE INDEX IF NOT EXISTS idx_memory_properties_entity
  ON memory_properties(entity_id);
CREATE INDEX IF NOT EXISTS idx_memory_relations_from
  ON memory_relations(from_object_id);
CREATE INDEX IF NOT EXISTS idx_memory_relations_to
  ON memory_relations(to_object_id);
CREATE INDEX IF NOT EXISTS idx_memory_time_refs_kind
  ON memory_time_refs(timeline_kind, time_kind, certainty);
CREATE INDEX IF NOT EXISTS idx_memory_time_links_target
  ON memory_time_links(target_object_id, time_role);
CREATE INDEX IF NOT EXISTS idx_memory_time_links_time_ref
  ON memory_time_links(time_ref_object_id);
CREATE INDEX IF NOT EXISTS idx_memory_sources_object
  ON memory_sources(object_id);
CREATE INDEX IF NOT EXISTS idx_memory_sources_source
  ON memory_sources(source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_memory_revisions_object_created
  ON memory_revisions(object_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_revisions_checkpoint
  ON memory_revisions(checkpoint_id, operation_index);
