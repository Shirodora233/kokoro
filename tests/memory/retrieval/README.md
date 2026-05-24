# Memory Retrieval Tests

Run local deterministic tests for candidate-aware retrieval and normalized prompt
retrieval:

```bash
.venv/bin/python -m tests.memory.retrieval.runner
```

These tests do not call an LLM. They cover candidate matching, direct/expanded
result labels, grouped results, strict one-hop link expansion, scope filtering,
unrelated candidates, and normalized event/entity prompt views that hide raw
link/time-link records.
