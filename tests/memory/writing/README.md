# Memory Writing Tests

Run deterministic tests for applying memory write plans:

```bash
.venv/bin/python -m tests.memory.writing.runner
```

These tests do not call an LLM. They verify that write plans are applied to the
in-memory store and that candidate ids are mapped to final record ids.
