# Memory Retrieval Tests

Run local deterministic tests for candidate-aware retrieval:

```bash
.venv/bin/python -m memory_retrieval_tests.runner
```

These tests do not call an LLM. They cover candidate matching, direct/expanded
result labels, strict one-hop link expansion, scope filtering, and unrelated
candidates.
