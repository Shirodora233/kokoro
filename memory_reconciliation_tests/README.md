# Memory Reconciliation Tests

Run deterministic tests for the baseline reconciler:

```bash
.venv/bin/python -m memory_reconciliation_tests.runner
```

These tests do not call an LLM. They verify that candidate retrieval groups are
turned into provider-neutral write plans.
