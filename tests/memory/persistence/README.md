# Memory Persistence Tests

Run PostgreSQL round-trip tests for normalized memory persistence:

```bash
.venv/bin/python -m tests.memory.persistence.runner
```

These tests require the configured PostgreSQL database from `.env`. They create
fixed test records, verify reads, and clean those records afterward.
