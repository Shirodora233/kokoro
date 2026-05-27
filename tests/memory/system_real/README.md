# Memory System Real Tests

These tests call the configured real LLM and run candidates through the full
in-memory memory runtime:

- `LLMMemoryExtractor`
- prepare-turn memory search snapshot
- commit-turn candidate matching
- deterministic reconciliation
- write-plan application
- active-memory refresh
- prompt-context retrieval

They are intentionally separate from deterministic `tests/memory/system/`.
Run them with:

```bash
.venv/bin/python -m tests.memory.system_real.runner
```

Use `--strict` when CI-like failure behavior is needed.
