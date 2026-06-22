CREATE EXTENSION IF NOT EXISTS vector;

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

DO $$
BEGIN
  IF to_regclass('public.memory_sources') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'memory_sources'
         AND column_name = 'memory_type'
     )
     AND NOT EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'memory_sources'
         AND column_name = 'object_id'
     )
  THEN
    IF to_regclass('public.memory_sources_legacy') IS NULL THEN
      ALTER TABLE memory_sources RENAME TO memory_sources_legacy;
    ELSE
      DROP TABLE memory_sources;
    END IF;
  END IF;

  IF to_regclass('public.memory_links') IS NOT NULL THEN
    IF to_regclass('public.memory_links_legacy') IS NULL THEN
      ALTER TABLE memory_links RENAME TO memory_links_legacy;
    ELSE
      DROP TABLE memory_links;
    END IF;
  END IF;

  IF to_regclass('public.memory_time_links') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'memory_time_links'
         AND column_name = 'target_type'
     )
  THEN
    IF to_regclass('public.memory_time_links_legacy') IS NULL THEN
      ALTER TABLE memory_time_links RENAME TO memory_time_links_legacy;
    ELSE
      DROP TABLE memory_time_links;
    END IF;
  END IF;
END $$;

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

CREATE TABLE IF NOT EXISTS memory_records (
  id TEXT PRIMARY KEY,
  memory_type TEXT NOT NULL,
  text TEXT NOT NULL,
  user_id TEXT,
  session_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_turn_id TEXT,
  created_checkpoint_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS memory_source_refs (
  memory_record_id TEXT NOT NULL,
  position INTEGER NOT NULL DEFAULT 0,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  quote TEXT,
  span_start INTEGER,
  span_end INTEGER,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_sources_legacy (
  id TEXT PRIMARY KEY,
  memory_type TEXT NOT NULL,
  memory_id TEXT NOT NULL,
  source_type TEXT NOT NULL,
  source_id TEXT NOT NULL,
  quote TEXT,
  span_start INTEGER,
  span_end INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_links_legacy (
  id TEXT PRIMARY KEY,
  user_id TEXT,
  from_type TEXT NOT NULL,
  from_id TEXT NOT NULL,
  to_type TEXT NOT NULL,
  to_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  reason TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  confidence TEXT NOT NULL DEFAULT 'medium',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_turn_id TEXT,
  created_checkpoint_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memory_time_links_legacy (
  id TEXT PRIMARY KEY,
  target_type TEXT NOT NULL,
  target_id TEXT NOT NULL,
  time_ref_id TEXT NOT NULL,
  time_role TEXT NOT NULL,
  confidence TEXT NOT NULL DEFAULT 'medium',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_turn_id TEXT,
  created_checkpoint_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

DO $$
BEGIN
  IF to_regclass('public.memory_events') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'memory_events'
         AND column_name = 'user_id'
     )
  THEN
    INSERT INTO memory_objects (
      id, object_type, user_id, session_id, scope, status, confidence,
      importance, created_turn_id, created_checkpoint_id, created_at,
      updated_at, merged_into_object_id, deleted_at, deleted_reason, metadata
    )
    SELECT
      id, 'event', user_id, session_id,
      CASE WHEN session_id IS NOT NULL THEN 'session'
           WHEN user_id IS NOT NULL THEN 'user'
           ELSE 'global' END,
      status, confidence, importance, created_turn_id, created_checkpoint_id,
      created_at, updated_at, merged_into_id, deleted_at, deleted_reason, metadata
    FROM memory_events
    ON CONFLICT (id) DO NOTHING;
  END IF;

  IF to_regclass('public.memory_descriptions') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'memory_descriptions'
         AND column_name = 'user_id'
     )
  THEN
    INSERT INTO memory_objects (
      id, object_type, user_id, session_id, scope, status, confidence,
      importance, created_turn_id, created_checkpoint_id, created_at,
      updated_at, merged_into_object_id, deleted_at, deleted_reason, metadata
    )
    SELECT
      id, 'description', user_id, session_id,
      CASE WHEN session_id IS NOT NULL THEN 'session'
           WHEN user_id IS NOT NULL THEN 'user'
           ELSE 'global' END,
      status, confidence, importance, created_turn_id, created_checkpoint_id,
      created_at, updated_at, merged_into_id, deleted_at, deleted_reason, metadata
    FROM memory_descriptions
    ON CONFLICT (id) DO NOTHING;
  END IF;

  IF to_regclass('public.memory_entities') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'memory_entities'
         AND column_name = 'user_id'
     )
  THEN
    INSERT INTO memory_objects (
      id, object_type, user_id, session_id, scope, status, confidence,
      importance, created_turn_id, created_checkpoint_id, created_at,
      updated_at, metadata
    )
    SELECT
      id, 'entity', user_id, session_id, scope, 'active',
      confidence, importance, created_turn_id, created_checkpoint_id,
      created_at, updated_at, metadata
    FROM memory_entities
    ON CONFLICT (id) DO NOTHING;

    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name = 'memory_entities'
        AND column_name = 'aliases'
    )
    THEN
      INSERT INTO memory_entity_aliases (entity_id, alias, position)
      SELECT id, alias, position - 1
      FROM memory_entities,
           jsonb_array_elements_text(aliases) WITH ORDINALITY AS alias_values(alias, position)
      ON CONFLICT (entity_id, alias) DO NOTHING;
    END IF;
  END IF;

  IF to_regclass('public.memory_properties') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'memory_properties'
         AND column_name = 'user_id'
     )
  THEN
    INSERT INTO memory_objects (
      id, object_type, user_id, session_id, scope, status, confidence,
      importance, created_turn_id, created_checkpoint_id, created_at,
      updated_at, merged_into_object_id, deleted_at, deleted_reason, metadata
    )
    SELECT
      id, 'property', user_id, session_id,
      CASE WHEN session_id IS NOT NULL THEN 'session'
           WHEN user_id IS NOT NULL THEN 'user'
           ELSE 'global' END,
      status, confidence, importance, created_turn_id, created_checkpoint_id,
      created_at, updated_at, merged_into_id, deleted_at, deleted_reason, metadata
    FROM memory_properties
    ON CONFLICT (id) DO NOTHING;
  END IF;

  IF to_regclass('public.memory_time_refs') IS NOT NULL
     AND EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public'
         AND table_name = 'memory_time_refs'
         AND column_name = 'created_turn_id'
     )
  THEN
    INSERT INTO memory_objects (
      id, object_type, user_id, session_id, scope, status, confidence,
      importance, created_turn_id, created_checkpoint_id, created_at,
      updated_at, metadata
    )
    SELECT
      id, 'time_ref',
      metadata->>'user_id', metadata->>'session_id',
      CASE WHEN metadata->>'session_id' IS NOT NULL THEN 'session'
           WHEN metadata->>'user_id' IS NOT NULL THEN 'user'
           ELSE 'global' END,
      'active', 'medium', 'low', created_turn_id, created_checkpoint_id,
      created_at, updated_at, metadata
    FROM memory_time_refs
    ON CONFLICT (id) DO NOTHING;
  END IF;
END $$;

INSERT INTO memory_objects (
  id, object_type, user_id, session_id, scope, status, confidence, importance,
  created_turn_id, created_checkpoint_id, created_at, updated_at, metadata
)
SELECT
  id,
  CASE memory_type WHEN 'link' THEN 'relation' ELSE memory_type END,
  COALESCE(user_id, metadata->>'user_id'),
  COALESCE(session_id, metadata->>'session_id'),
  CASE WHEN COALESCE(session_id, metadata->>'session_id') IS NOT NULL THEN 'session'
       WHEN COALESCE(user_id, metadata->>'user_id') IS NOT NULL THEN 'user'
       ELSE 'global' END,
  COALESCE(NULLIF(metadata->>'status', ''), 'active'),
  COALESCE(NULLIF(metadata->>'confidence', ''), 'medium'),
  COALESCE(NULLIF(metadata->>'importance', ''), 'medium'),
  created_turn_id,
  created_checkpoint_id,
  created_at,
  updated_at,
  metadata
FROM memory_records
WHERE to_regclass('public.memory_records') IS NOT NULL
  AND memory_type IN (
    'event', 'description', 'entity', 'property', 'link',
    'time_ref', 'time_link', 'summary'
  )
ON CONFLICT (id) DO NOTHING;

INSERT INTO memory_events (id, title, summary, event_type)
SELECT id, text, metadata->>'summary', metadata->>'event_type'
FROM memory_records
WHERE to_regclass('public.memory_records') IS NOT NULL
  AND memory_type = 'event'
ON CONFLICT (id) DO NOTHING;

INSERT INTO memory_descriptions (id, event_id, content, description_type)
SELECT
  id,
  metadata->>'attached_to_record_id',
  text,
  metadata->>'description_type'
FROM memory_records
WHERE to_regclass('public.memory_records') IS NOT NULL
  AND memory_type = 'description'
  AND metadata->>'attached_to_record_id' IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM memory_events
    WHERE memory_events.id = memory_records.metadata->>'attached_to_record_id'
  )
ON CONFLICT (id) DO NOTHING;

INSERT INTO memory_entities (id, name, entity_type, identity_summary)
SELECT
  id,
  text,
  COALESCE(NULLIF(metadata->>'entity_type', ''), 'unknown'),
  metadata->>'identity_summary'
FROM memory_records
WHERE to_regclass('public.memory_records') IS NOT NULL
  AND memory_type = 'entity'
ON CONFLICT (id) DO NOTHING;

INSERT INTO memory_entity_aliases (entity_id, alias, position)
SELECT
  id,
  alias,
  position - 1
FROM memory_records,
     jsonb_array_elements_text(
       CASE
         WHEN jsonb_typeof(metadata->'aliases') = 'array' THEN metadata->'aliases'
         ELSE '[]'::jsonb
       END
     ) WITH ORDINALITY AS alias_values(alias, position)
WHERE to_regclass('public.memory_records') IS NOT NULL
  AND memory_type = 'entity'
ON CONFLICT (entity_id, alias) DO NOTHING;

INSERT INTO memory_properties (id, entity_id, content, property_type)
SELECT
  id,
  metadata->>'attached_to_record_id',
  text,
  metadata->>'property_type'
FROM memory_records
WHERE to_regclass('public.memory_records') IS NOT NULL
  AND memory_type = 'property'
  AND metadata->>'attached_to_record_id' IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM memory_entities
    WHERE memory_entities.id = memory_records.metadata->>'attached_to_record_id'
  )
ON CONFLICT (id) DO NOTHING;

INSERT INTO memory_relations (id, from_object_id, to_object_id, relation_type, reason)
SELECT
  id,
  metadata->>'from_record_id',
  metadata->>'to_record_id',
  metadata->>'relation_type',
  metadata->>'write_reason'
FROM memory_records
WHERE to_regclass('public.memory_records') IS NOT NULL
  AND memory_type = 'link'
  AND metadata->>'from_record_id' IS NOT NULL
  AND metadata->>'to_record_id' IS NOT NULL
  AND metadata->>'relation_type' IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM memory_objects
    WHERE memory_objects.id = memory_records.metadata->>'from_record_id'
  )
  AND EXISTS (
    SELECT 1 FROM memory_objects
    WHERE memory_objects.id = memory_records.metadata->>'to_record_id'
  )
ON CONFLICT (from_object_id, to_object_id, relation_type) DO NOTHING;

INSERT INTO memory_time_refs (
  id, raw_text, time_kind, timeline_kind, certainty, anchor_timezone,
  anchor_utc_offset, anchor_message_id, resolved_start, resolved_end,
  granularity, description, duration_text, recurrence_text
)
SELECT
  id,
  COALESCE(NULLIF(metadata->>'raw_text', ''), text),
  COALESCE(NULLIF(metadata->>'time_kind', ''), 'vague'),
  COALESCE(NULLIF(metadata->>'timeline_kind', ''), 'real_world'),
  COALESCE(NULLIF(metadata->>'certainty', ''), 'unknown'),
  COALESCE(NULLIF(metadata->>'anchor_timezone', ''), 'UTC'),
  COALESCE(NULLIF(metadata->>'anchor_utc_offset', ''), '+00:00'),
  metadata->>'anchor_message_id',
  metadata->>'resolved_start',
  metadata->>'resolved_end',
  metadata->>'granularity',
  metadata->>'description',
  metadata->>'duration_text',
  metadata->>'recurrence_text'
FROM memory_records
WHERE to_regclass('public.memory_records') IS NOT NULL
  AND memory_type = 'time_ref'
ON CONFLICT (id) DO NOTHING;

INSERT INTO memory_time_links (id, target_object_id, time_ref_object_id, time_role)
SELECT
  id,
  metadata->>'target_record_id',
  metadata->>'time_ref_record_id',
  metadata->>'time_role'
FROM memory_records
WHERE to_regclass('public.memory_records') IS NOT NULL
  AND memory_type = 'time_link'
  AND metadata->>'target_record_id' IS NOT NULL
  AND metadata->>'time_ref_record_id' IS NOT NULL
  AND metadata->>'time_role' IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM memory_objects
    WHERE memory_objects.id = memory_records.metadata->>'target_record_id'
  )
  AND EXISTS (
    SELECT 1 FROM memory_time_refs
    WHERE memory_time_refs.id = memory_records.metadata->>'time_ref_record_id'
  )
ON CONFLICT (target_object_id, time_ref_object_id, time_role) DO NOTHING;

INSERT INTO memory_objects (
  id, object_type, user_id, session_id, scope, status, confidence, importance,
  created_turn_id, created_checkpoint_id, created_at, updated_at, metadata
)
SELECT
  id, 'relation', user_id, NULL, 'global', status, confidence, 'medium',
  created_turn_id, created_checkpoint_id, created_at, updated_at, metadata
FROM memory_links_legacy
WHERE to_regclass('public.memory_links_legacy') IS NOT NULL
ON CONFLICT (id) DO NOTHING;

INSERT INTO memory_relations (id, from_object_id, to_object_id, relation_type, reason)
SELECT id, from_id, to_id, relation_type, reason
FROM memory_links_legacy
WHERE to_regclass('public.memory_links_legacy') IS NOT NULL
  AND EXISTS (SELECT 1 FROM memory_objects WHERE memory_objects.id = memory_links_legacy.from_id)
  AND EXISTS (SELECT 1 FROM memory_objects WHERE memory_objects.id = memory_links_legacy.to_id)
ON CONFLICT (from_object_id, to_object_id, relation_type) DO NOTHING;

INSERT INTO memory_objects (
  id, object_type, user_id, session_id, scope, status, confidence, importance,
  created_turn_id, created_checkpoint_id, created_at, updated_at, metadata
)
SELECT
  id, 'time_link', metadata->>'user_id', metadata->>'session_id',
  CASE WHEN metadata->>'session_id' IS NOT NULL THEN 'session'
       WHEN metadata->>'user_id' IS NOT NULL THEN 'user'
       ELSE 'global' END,
  'active', confidence, 'low', created_turn_id, created_checkpoint_id,
  created_at, updated_at, metadata
FROM memory_time_links_legacy
WHERE to_regclass('public.memory_time_links_legacy') IS NOT NULL
ON CONFLICT (id) DO NOTHING;

INSERT INTO memory_time_links (id, target_object_id, time_ref_object_id, time_role)
SELECT id, target_id, time_ref_id, time_role
FROM memory_time_links_legacy
WHERE to_regclass('public.memory_time_links_legacy') IS NOT NULL
  AND EXISTS (SELECT 1 FROM memory_objects WHERE memory_objects.id = memory_time_links_legacy.target_id)
  AND EXISTS (SELECT 1 FROM memory_time_refs WHERE memory_time_refs.id = memory_time_links_legacy.time_ref_id)
ON CONFLICT (target_object_id, time_ref_object_id, time_role) DO NOTHING;

INSERT INTO memory_sources (
  id, object_id, source_type, source_id, quote, span_start, span_end,
  created_at, metadata
)
SELECT
  id, memory_id, source_type, source_id, quote, span_start, span_end,
  created_at, metadata
FROM memory_sources_legacy
WHERE to_regclass('public.memory_sources_legacy') IS NOT NULL
  AND EXISTS (SELECT 1 FROM memory_objects WHERE memory_objects.id = memory_sources_legacy.memory_id)
ON CONFLICT (id) DO NOTHING;

INSERT INTO memory_sources (
  id, object_id, source_type, source_id, quote, span_start, span_end,
  metadata
)
SELECT
  'src_migrated_' || md5(
    memory_record_id || ':' || position::text || ':' || source_type || ':' || source_id
  ),
  memory_record_id,
  source_type,
  source_id,
  quote,
  span_start,
  span_end,
  metadata
FROM memory_source_refs
WHERE to_regclass('public.memory_source_refs') IS NOT NULL
  AND EXISTS (SELECT 1 FROM memory_objects WHERE memory_objects.id = memory_source_refs.memory_record_id);

DELETE FROM memory_objects AS object
WHERE object.object_type = 'event'
  AND NOT EXISTS (SELECT 1 FROM memory_events WHERE memory_events.id = object.id);
DELETE FROM memory_objects AS object
WHERE object.object_type = 'description'
  AND NOT EXISTS (SELECT 1 FROM memory_descriptions WHERE memory_descriptions.id = object.id);
DELETE FROM memory_objects AS object
WHERE object.object_type = 'entity'
  AND NOT EXISTS (SELECT 1 FROM memory_entities WHERE memory_entities.id = object.id);
DELETE FROM memory_objects AS object
WHERE object.object_type = 'property'
  AND NOT EXISTS (SELECT 1 FROM memory_properties WHERE memory_properties.id = object.id);
DELETE FROM memory_objects AS object
WHERE object.object_type = 'relation'
  AND NOT EXISTS (SELECT 1 FROM memory_relations WHERE memory_relations.id = object.id);
DELETE FROM memory_objects AS object
WHERE object.object_type = 'time_ref'
  AND NOT EXISTS (SELECT 1 FROM memory_time_refs WHERE memory_time_refs.id = object.id);
DELETE FROM memory_objects AS object
WHERE object.object_type = 'time_link'
  AND NOT EXISTS (SELECT 1 FROM memory_time_links WHERE memory_time_links.id = object.id);

ALTER TABLE memory_events
  DROP COLUMN IF EXISTS user_id,
  DROP COLUMN IF EXISTS session_id,
  DROP COLUMN IF EXISTS status,
  DROP COLUMN IF EXISTS confidence,
  DROP COLUMN IF EXISTS importance,
  DROP COLUMN IF EXISTS created_at,
  DROP COLUMN IF EXISTS updated_at,
  DROP COLUMN IF EXISTS merged_into_id,
  DROP COLUMN IF EXISTS deleted_at,
  DROP COLUMN IF EXISTS deleted_reason,
  DROP COLUMN IF EXISTS created_turn_id,
  DROP COLUMN IF EXISTS created_checkpoint_id,
  DROP COLUMN IF EXISTS created_checkpoint_sequence,
  DROP COLUMN IF EXISTS metadata;

ALTER TABLE memory_descriptions
  DROP COLUMN IF EXISTS user_id,
  DROP COLUMN IF EXISTS session_id,
  DROP COLUMN IF EXISTS status,
  DROP COLUMN IF EXISTS confidence,
  DROP COLUMN IF EXISTS importance,
  DROP COLUMN IF EXISTS created_at,
  DROP COLUMN IF EXISTS updated_at,
  DROP COLUMN IF EXISTS merged_into_id,
  DROP COLUMN IF EXISTS deleted_at,
  DROP COLUMN IF EXISTS deleted_reason,
  DROP COLUMN IF EXISTS created_turn_id,
  DROP COLUMN IF EXISTS created_checkpoint_id,
  DROP COLUMN IF EXISTS created_checkpoint_sequence,
  DROP COLUMN IF EXISTS metadata;

ALTER TABLE memory_entities
  DROP COLUMN IF EXISTS user_id,
  DROP COLUMN IF EXISTS session_id,
  DROP COLUMN IF EXISTS scope,
  DROP COLUMN IF EXISTS aliases,
  DROP COLUMN IF EXISTS confidence,
  DROP COLUMN IF EXISTS importance,
  DROP COLUMN IF EXISTS created_at,
  DROP COLUMN IF EXISTS updated_at,
  DROP COLUMN IF EXISTS created_turn_id,
  DROP COLUMN IF EXISTS created_checkpoint_id,
  DROP COLUMN IF EXISTS created_checkpoint_sequence,
  DROP COLUMN IF EXISTS metadata;

ALTER TABLE memory_properties
  DROP COLUMN IF EXISTS user_id,
  DROP COLUMN IF EXISTS session_id,
  DROP COLUMN IF EXISTS status,
  DROP COLUMN IF EXISTS confidence,
  DROP COLUMN IF EXISTS importance,
  DROP COLUMN IF EXISTS created_at,
  DROP COLUMN IF EXISTS updated_at,
  DROP COLUMN IF EXISTS invalidated_by,
  DROP COLUMN IF EXISTS merged_into_id,
  DROP COLUMN IF EXISTS deleted_at,
  DROP COLUMN IF EXISTS deleted_reason,
  DROP COLUMN IF EXISTS created_turn_id,
  DROP COLUMN IF EXISTS created_checkpoint_id,
  DROP COLUMN IF EXISTS created_checkpoint_sequence,
  DROP COLUMN IF EXISTS metadata;

ALTER TABLE memory_time_refs
  DROP COLUMN IF EXISTS created_at,
  DROP COLUMN IF EXISTS updated_at,
  DROP COLUMN IF EXISTS created_turn_id,
  DROP COLUMN IF EXISTS created_checkpoint_id,
  DROP COLUMN IF EXISTS created_checkpoint_sequence,
  DROP COLUMN IF EXISTS metadata;

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

DROP TABLE IF EXISTS memory_source_refs;
DROP TABLE IF EXISTS memory_records;
DROP TABLE IF EXISTS memory_sources_legacy;
DROP TABLE IF EXISTS memory_links_legacy;
DROP TABLE IF EXISTS memory_time_links_legacy;

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

CREATE TABLE IF NOT EXISTS memory_object_embeddings (
    object_id TEXT PRIMARY KEY REFERENCES memory_objects(id) ON DELETE CASCADE,
    embedding vector(1536) NOT NULL,
    model TEXT NOT NULL,
    searchable_text TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_object_embeddings_vector
    ON memory_object_embeddings USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX IF NOT EXISTS idx_memory_object_embeddings_model
    ON memory_object_embeddings(model);
