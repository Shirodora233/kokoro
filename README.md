# Kokoro Conversation System

一个基于 OpenAI Python SDK 的持久化 LLM 对话系统。当前默认使用 PostgreSQL 持久化，并保留 JSON store 作为本地 fallback / 迁移来源：

- `conversation/data/users.json`
- `conversation/data/sessions.json`
- `conversation/data/messages.json`
- `conversation/data/schema.json`
- `conversation/storage/postgres/schema.sql`

## 配置

系统会读取 `.env` 中的这些字段：

```env
LLM_API_KEY="..."
LLM_BASE_URL="..."
LLM_MODEL="..."
CONVERSATION_STORE="postgres"
CONVERSATION_DATABASE_URL="postgresql://kokoro:...@127.0.0.1:54330/kokoro"
CONVERSATION_TIMEZONE="Asia/Shanghai"
MEMORY_EXTRACTION_ENABLED="true"
MEMORY_EXTRACTION_MODEL=""
MEMORY_EXTRACTION_TEMPERATURE="0.0"
MEMORY_EXTRACTION_MAX_CONTEXT_MESSAGES="20"
```

也支持 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL` 作为兼容字段。
可从 `.env.example` 复制字段名后填入自己的配置。

如果需要临时回退到 JSON 文档存储：

```env
CONVERSATION_STORE="json"
```

## PostgreSQL

本地开发可以用 Docker 启动 PostgreSQL：

```bash
docker run -d --name kokoro-postgres \
  -e POSTGRES_USER=kokoro \
  -e POSTGRES_PASSWORD=<strong-password> \
  -e POSTGRES_DB=kokoro \
  -p 127.0.0.1:54330:5432 \
  -v kokoro-postgres-data:/var/lib/postgresql/data \
  postgres:16
```

从 JSON 表迁移到 PostgreSQL：

```bash
.venv/bin/python -m conversation.storage.migrate_json_to_postgres --replace
```

也可以显式传入连接串：

```bash
.venv/bin/python -m conversation.storage.migrate_json_to_postgres \
  --database-url "postgresql://kokoro:<strong-password>@127.0.0.1:54330/kokoro" \
  --replace
```

## 测试

测试代码统一放在 `tests/` 下。memory 子系统按能力拆分在 `tests/memory/`：

- `retrieval/`
- `reconciliation/`
- `writing/`
- `system/`
- `persistence/`
- `extractor_real/`
- `system_real/`

运行快速 deterministic suite：

```bash
.venv/bin/python -m tests.memory.run_all
```

包含 PostgreSQL persistence 测试：

```bash
.venv/bin/python -m tests.memory.run_all --postgres
```

包含真实 LLM 测试：

```bash
.venv/bin/python -m tests.memory.run_all --real-llm --env-file .env
```

## 使用

安装依赖：

```bash
.venv/bin/python -m pip install -r requirements.txt
```

创建用户：

```bash
.venv/bin/python -m conversation.cli user alice --display-name Alice
```

列出用户：

```bash
.venv/bin/python -m conversation.cli users
```

创建会话：

```bash
.venv/bin/python -m conversation.cli session alice --title "Daily chat" --system-prompt "You are helpful."
```

交互式对话：

```bash
.venv/bin/python -m conversation.cli chat alice
```

查看会话记录：

```bash
.venv/bin/python -m conversation.cli transcript <session_id>
```

分页查看完整会话记录：

```bash
.venv/bin/python -m conversation.cli history <session_id> --page 1 --page-size 50
```

查看将提供给大模型的上下文：

```bash
.venv/bin/python -m conversation.cli context <session_id>
```

调整大模型上下文起点指针：

```bash
.venv/bin/python -m conversation.cli set-context-start <session_id> 4
```

预留的会话查询接口：

```bash
.venv/bin/python -m conversation.cli query <session_id> "keyword"
```

当前查询接口会返回 `not implemented`，等待后续接入数据库或记忆检索系统。

重命名或归档会话：

```bash
.venv/bin/python -m conversation.cli rename-session <session_id> "New title"
.venv/bin/python -m conversation.cli archive-session <session_id>
```

删除会话及其消息：

```bash
.venv/bin/python -m conversation.cli delete-session <session_id>
```

删除用户：

```bash
.venv/bin/python -m conversation.cli delete-user alice
```

如果用户名下还有会话或消息，默认会拒绝删除；需要一起级联删除时显式加 `--cascade`：

```bash
.venv/bin/python -m conversation.cli delete-user alice --cascade
```

删除全部用户、会话和消息：

```bash
.venv/bin/python -m conversation.cli delete-all
```

## 代码入口

应用内集成优先使用自定义接口文件 `conversation/api.py`：

```python
from conversation import create_default_api

api = create_default_api()
session = api.open_session("alice", title="Daily chat")
reply = api.ask(session["id"], "你好")
print(reply["assistant_message"]["content"])
```

## 会话上下文

会话历史分页和大模型上下文窗口管理位于 `conversation/context/`。它属于对话系统内部能力，不作为记忆系统入口：

- `SessionManager.get_full_history(...)`：分页获取某个 session 的完整聊天记录。
- `SessionManager.get_model_context(...)`：按 `context_start_index` 指针返回需要提供给大模型的上下文。
- `SessionManager.set_context_start_index(...)`：修改上下文起点指针。
- `SessionManager.query_messages(...)`：预留查询接口，当前暂不实现。

LLM provider 抽象位于 `llm/`，包括 `ChatClient`、`ChatMessageParam`、`LLMConfig` 和 `OpenAIChatClient`。后续 `conversation/` 和 `memory/` 都应该依赖 `llm/`，避免记忆系统反向依赖对话系统。

## 记忆运行时

`memory/` 是独立于 `conversation/` 的记忆系统边界。当前 runtime 仍由
`InMemoryMemorySystem` 组合组件，但 store / retriever / persistence 都可以替换：

- 默认通过 `LLMMemoryExtractor` 从新消息和近期上下文中抽取候选记忆。
- PostgreSQL 后端会同时写入 generic `memory_records` 和范式化 memory tables。
- prompt retrieval 在 PostgreSQL 后端使用 normalized retriever，从 event/entity/property/time
  关系中组装干净上下文，不把 raw `link` / `time_link` 直接塞进 prompt。
- candidate retrieval 仍使用 generic `MemoryStore` 给 reconciler 查重、reuse 和 attach。
- 可通过传入 `NoopMemorySystem` 临时关闭记忆链路。

抽取实现拆在 `memory/extraction/`：`pipeline.py` 负责流程编排，`llm.py` 只负责调用模型，`prompt.py`、`parser.py`、`normalizer.py` 分别负责提示词、JSON 解析和候选规范化。

如果需要临时关闭 LLM 记忆抽取，可以设置：

```env
MEMORY_EXTRACTION_ENABLED="false"
```

HTTP 接口也已经暴露：

```text
GET   /api/sessions/<session_id>/history?page=1&page_size=50
GET   /api/sessions/<session_id>/context
PATCH /api/sessions/<session_id>/context
GET   /api/sessions/<session_id>/query?q=keyword&page=1&page_size=50
```

`PATCH /context` 的请求体示例：

```json
{"context_start_index": 4}
```
