# Memory Tests

Memory tests are grouped by subsystem:

- `retrieval/`：candidate-aware retrieval, normalized search, and normalized prompt retrieval.
- `extraction/`：deterministic candidate parsing, coalescing, validation, and normalization.
- `reconciliation/`：deterministic write-plan generation.
- `writing/`：write-plan application to a memory store.
- `system/`：deterministic memory runtime orchestration.
- `persistence/`：PostgreSQL normalized persistence round trips.
- `extractor_real/`：real LLM extractor behavior and reports.
- `system_real/`：real LLM end-to-end memory runtime reports.
- `postgres_real/`：real LLM end-to-end memory runtime with PostgreSQL normalized persistence.

Run the fast deterministic suite:

```bash
.venv/bin/python -m tests.memory.run_all
```

Include PostgreSQL persistence tests:

```bash
.venv/bin/python -m tests.memory.run_all --postgres
```

Include real LLM tests:

```bash
.venv/bin/python -m tests.memory.run_all --real-llm --env-file .env
```

Include the real LLM PostgreSQL persistence scenario:

```bash
.venv/bin/python -m tests.memory.run_all --postgres --real-llm --env-file .env
```

Real LLM runs write timestamped Markdown reports under their own `reports/`
directories.
