# Memory Extractor Tests

这个目录用于真实调用 `LLMMemoryExtractor`，观察当前抽取器在多组上下文中的行为。

运行：

```bash
.venv/bin/python -m memory_extractor_tests.runner --env-file .env
```

默认会读取 `.env` 中的 LLM 配置，调用真实模型，并生成：

```text
memory_extractor_tests/reports/latest.md
```

这些测试只覆盖当前 extractor：prompt 构造、LLM 调用、JSON 解析、候选规范化。它们不会测试 memory store、merge/update、冲突解决或检索。
