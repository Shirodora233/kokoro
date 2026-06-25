CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  system_prompt TEXT,
  model TEXT,
  temperature DOUBLE PRECISION,
  max_context_messages INTEGER,
  context_start_index INTEGER NOT NULL DEFAULT 0 CHECK (context_start_index >= 0),
  head_checkpoint_id TEXT,
  root_session_id TEXT,
  parent_session_id TEXT,
  base_checkpoint_id TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  archived_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
  content TEXT NOT NULL,
  model TEXT,
  token_usage JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_turns (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  user_message_id TEXT,
  assistant_message_id TEXT,
  checkpoint_id TEXT,
  status TEXT NOT NULL DEFAULT 'llm_running'
    CHECK (status IN ('preparing', 'llm_running', 'committing', 'committed', 'failed')),
  idempotency_key TEXT,
  debug_trace_id TEXT,
  memory_status TEXT NOT NULL DEFAULT 'not_run'
    CHECK (memory_status IN ('not_run', 'committed', 'failed')),
  error TEXT,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (session_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS conversation_checkpoints (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_id TEXT REFERENCES conversation_turns(id) ON DELETE SET NULL,
  parent_checkpoint_id TEXT REFERENCES conversation_checkpoints(id) ON DELETE SET NULL,
  assistant_message_id TEXT,
  sequence INTEGER NOT NULL CHECK (sequence >= 0),
  label TEXT,
  session_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  active_memory_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS checkpoint_ancestry (
  ancestor_checkpoint_id TEXT NOT NULL REFERENCES conversation_checkpoints(id) ON DELETE CASCADE,
  descendant_checkpoint_id TEXT NOT NULL REFERENCES conversation_checkpoints(id) ON DELETE CASCADE,
  depth INTEGER NOT NULL CHECK (depth >= 0),
  PRIMARY KEY (ancestor_checkpoint_id, descendant_checkpoint_id)
);

CREATE TABLE IF NOT EXISTS session_branches (
  session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
  root_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  parent_session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  base_checkpoint_id TEXT NOT NULL REFERENCES conversation_checkpoints(id) ON DELETE CASCADE,
  base_sequence INTEGER NOT NULL CHECK (base_sequence >= 0),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_memory_debug_traces (
  trace_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  turn_id TEXT REFERENCES conversation_turns(id) ON DELETE CASCADE,
  user_message_id TEXT,
  assistant_message_id TEXT,
  checkpoint_id TEXT REFERENCES conversation_checkpoints(id) ON DELETE CASCADE,
  checkpoint_sequence INTEGER,
  memory_status TEXT NOT NULL DEFAULT 'not_run',
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  trace JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TEXT NOT NULL
);

ALTER TABLE messages ADD COLUMN IF NOT EXISTS turn_id TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS checkpoint_id TEXT;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS sequence INTEGER;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS head_checkpoint_id TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS root_session_id TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS parent_session_id TEXT;
ALTER TABLE sessions ADD COLUMN IF NOT EXISTS base_checkpoint_id TEXT;

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_updated_at ON sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session_created_at ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_id);
CREATE INDEX IF NOT EXISTS idx_messages_session_sequence ON messages(session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_messages_turn_id ON messages(turn_id);
CREATE INDEX IF NOT EXISTS idx_messages_checkpoint_id ON messages(checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_conversation_turns_session_status ON conversation_turns(session_id, status);
CREATE INDEX IF NOT EXISTS idx_conversation_turns_idempotency ON conversation_turns(session_id, idempotency_key);
CREATE INDEX IF NOT EXISTS idx_conversation_checkpoints_session_sequence ON conversation_checkpoints(session_id, sequence DESC);
CREATE INDEX IF NOT EXISTS idx_checkpoint_ancestry_descendant_depth
  ON checkpoint_ancestry(descendant_checkpoint_id, depth);
CREATE INDEX IF NOT EXISTS idx_checkpoint_ancestry_ancestor
  ON checkpoint_ancestry(ancestor_checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_session_branches_parent ON session_branches(parent_session_id, base_checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_conversation_memory_debug_session_sequence
  ON conversation_memory_debug_traces(session_id, checkpoint_sequence);
CREATE INDEX IF NOT EXISTS idx_conversation_memory_debug_checkpoint
  ON conversation_memory_debug_traces(checkpoint_id);
CREATE INDEX IF NOT EXISTS idx_conversation_memory_debug_messages
  ON conversation_memory_debug_traces(user_message_id, assistant_message_id);
