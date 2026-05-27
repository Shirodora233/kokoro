# Memory System Tests

These tests exercise the in-memory composition layer:

- extraction candidates are scoped to the current turn,
- prepare builds a reusable memory search snapshot before the LLM call,
- commit reuses that snapshot for candidate matching and reconciliation,
- write plans are applied to the in-memory store,
- active memory context and prompt retrieval are refreshed from written records.

They use deterministic fake extractors rather than a real LLM so this layer can
guard orchestration behavior separately from extraction quality.
