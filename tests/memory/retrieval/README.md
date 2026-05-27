# Memory Retrieval Tests

Run local deterministic tests for candidate-aware retrieval and normalized prompt
retrieval:

```bash
.venv/bin/python -m tests.memory.retrieval.runner
```

These tests do not call an LLM. They cover candidate matching, direct/expanded
result labels, grouped results, strict one-hop link expansion, scope filtering,
unrelated candidates, and normalized event/entity prompt views that hide raw
link/time-link records. They also cover the normalized lookup boundary, including
hydrating a description hit back to its parent event without relying on the
recent event/entity pool, plus deterministic ranking rules for lookup hits.
