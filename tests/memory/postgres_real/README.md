# Memory PostgreSQL Real Tests

These tests call the configured real LLM and run the memory turn through
PostgreSQL-backed generic and normalized persistence:

- `LLMMemoryExtractor`
- prepare-turn normalized retrieval
- commit-turn write-plan application
- PostgreSQL generic memory store
- PostgreSQL normalized memory tables
- duplicate natural-link checks

They target issues that only appear after real extraction output is synced into
normalized PostgreSQL rows. Run them with:

```bash
.venv/bin/python -m tests.memory.postgres_real.runner --env-file .env --strict
```

Use `--keep-data` when the generated PostgreSQL rows should remain available
for manual inspection.
