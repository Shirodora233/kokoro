# Kokoro Conversation System

一个基于 OpenAI Python SDK 的持久化 LLM 对话系统。当前不接入数据库，而是用数据库标准设计把数据拆成 JSON 文档表：

- `conversation/data/users.json`
- `conversation/data/sessions.json`
- `conversation/data/messages.json`
- `conversation/data/schema.json`

## 配置

系统会读取 `.env` 中的这些字段：

```env
LLM_API_KEY="..."
LLM_BASE_URL="..."
LLM_MODEL="..."
```

也支持 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL` 作为兼容字段。
可从 `.env.example` 复制字段名后填入自己的配置。

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

## 会话管理

会话管理已经抽象到和 `conversation` 平级的 `session_management/` 包，后续接入记忆管理系统时可以优先扩展这里：

- `SessionManager.get_full_history(...)`：分页获取某个 session 的完整聊天记录。
- `SessionManager.get_model_context(...)`：按 `context_start_index` 指针返回需要提供给大模型的上下文。
- `SessionManager.set_context_start_index(...)`：修改上下文起点指针。
- `SessionManager.query_messages(...)`：预留查询接口，当前暂不实现。

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
