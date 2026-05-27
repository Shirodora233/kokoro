# Memory Reconciliation Tests

Run deterministic tests for the baseline reconciler:

```bash
.venv/bin/python -m tests.memory.reconciliation.runner
```

These tests do not call an LLM. They verify that candidate match groups are
turned into provider-neutral write plans.
