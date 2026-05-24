# Memory System Tests

These tests exercise the in-memory composition layer:

- extraction candidates are scoped to the current turn,
- candidate retrieval feeds reconciliation,
- write plans are applied to the in-memory store,
- active memory context and prompt retrieval are refreshed from written records.

They use deterministic fake extractors rather than a real LLM so this layer can
guard orchestration behavior separately from extraction quality.
