# Conversation Checkpoint / Branching Design

本文档描述 conversation 与 memory 的完成点、存档和分支语义。它不描述前端交互；前端可以把这些能力包装成“存档 / 读档 / 从这里继续”。

## 1. 核心概念

- `Turn`：一次用户消息到一次 assistant 回复的完整处理过程。
- `Checkpoint`：一个 assistant 回复完成后的稳定状态点。
- `Savepoint`：被用户命名或收藏的 checkpoint，本质仍然是 checkpoint metadata。
- `Branch session`：从某个 checkpoint 派生的新 session。原 session 不删除、不回滚。

系统只把 checkpoint 视为可恢复状态。未到 checkpoint 的中间状态不应该出现在普通 transcript 中。

## 2. 原子提交边界

LLM 调用不放在数据库事务里。一次发送消息的推荐流程是：

1. 生成临时 user message，不立即写库。
2. 用已提交历史和临时 user message 调用 `memory.prepare_turn(...)`。
3. 调用 LLM 得到 assistant 回复。
4. 开启 PostgreSQL transaction，并锁定目标 session。
5. 写入 user message、assistant message、memory writes 和 checkpoint。
6. commit 后刷新进程内 active memory cache。

如果 transaction 失败，数据库回到上一个 checkpoint。用户消息、assistant 消息和 memory 写入都不会半提交。

memory 写入默认不阻断基础聊天能力。memory commit 失败时，应回滚 memory 部分，仍提交 user/assistant message 和 checkpoint，并在 checkpoint metadata 中标记 `memory_status=failed`。

## 3. Branch 语义

手动回档默认创建新 branch session：

- 原 session 完整保留。
- 新 session 记录 `base_checkpoint_id`。
- 新 session 的 transcript = base checkpoint 之前的祖先消息 + 新 session 自己的新消息。
- memory retrieval = base checkpoint 之前的祖先 memory + 新 session 自己的新 memory + global/user memory。

不做默认原地回滚。未来如需原地回滚，应只标记后续消息和 memory 为 reverted，不做物理删除。

## 4. PostgreSQL Only

conversation 运行时只支持 PostgreSQL backend。checkpoint/branch 是基础能力，不再提供 JSON 持久化或无 checkpoint 降级路径。

原因是 checkpoint、turn、message、memory writes 和 debug trace 需要在同一个 PostgreSQL transaction 边界内提交，才能避免服务器中断后留下半状态。

## 5. Recovery

`conversation_turns` 允许出现未完成状态，例如服务器在 LLM 调用之后、最终 transaction 之前崩溃。服务启动时可以把未完成 turn 标记为 `failed`。由于这些 turn 没有 committed checkpoint，普通 transcript 不会看到半状态。
