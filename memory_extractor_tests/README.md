# Memory Extractor Tests

这个目录用于真实调用 `LLMMemoryExtractor`，观察当前抽取器在多组上下文中的行为。

运行：

```bash
.venv/bin/python -m memory_extractor_tests.runner --env-file .env
```

默认会读取 `.env` 中的 LLM 配置，调用真实模型，并生成不覆盖旧报告的时间戳文件：

```text
memory_extractor_tests/reports/YYYYMMDDTHHMMSSZ.md
```

如需指定固定路径，可以传入 `--report-path`。

这些测试只覆盖当前 extractor：prompt 构造、LLM 调用、聚合 JSON 解析、候选校验，以及拆分为当前 `MemoryRecord` 的过程。报告会记录每个 case 的原始 LLM 输入和输出。它们不会测试 memory store、merge/update、冲突解决或检索。
