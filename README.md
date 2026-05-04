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
