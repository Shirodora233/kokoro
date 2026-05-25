# 记忆系统处理流程

本文档只描述记忆系统和对话系统之间的处理流程与职责边界，不重复数据库表结构设计。表结构见 `docs/database_design.md`。

## 1. 目标

记忆系统是独立模块，不是 conversation 的子功能。它应该能够处理对话消息，也应该能在未来处理文件、网页、手动笔记等非对话输入。

当前第一阶段目标：

- conversation 收到新消息后，把新消息和必要上下文交给 memory。
- memory 基于上下文判断哪些内容值得沉淀为长期记忆。
- memory 返回可注入 LLM prompt 的记忆上下文。
- memory 返回对 conversation 上下文窗口的维护建议。
- conversation 保留 messages/session 的数据所有权，负责执行上下文窗口变更。

## 2. 模块职责

### conversation

conversation 负责事实动作：

- 保存用户消息和助手消息。
- 维护 `users`、`sessions`、`messages`。
- 维护当前 session 的短期上下文窗口。
- 调用 LLM 生成助手回复。
- 执行 memory 返回的上下文维护建议。

conversation 不负责判断长期记忆是否重要，也不负责决定什么时候压缩旧上下文。

### memory

memory 负责认知策略：

- 接收带上下文的新消息。
- 判断是否需要抽取、更新、合并或失效记忆。
- 判断当前对话上下文是否需要压缩。
- 返回可注入 LLM 的记忆上下文。
- 返回上下文维护建议，例如压缩某段消息或移动上下文起点。

memory 不直接修改 conversation 的 session 或 messages。

### llm

`llm/` 是共享模型 provider 抽象。conversation 和 memory 都可以依赖它，但 `llm/` 不依赖它们。

## 3. Turn 输入

conversation 调用 memory 时，应传入一个 `MemoryTurnInput`：

```python
MemoryTurnInput(
    user_id="usr_001",
    session_id="ses_001",
    new_message=MemoryInputMessage(...),
    timezone="Asia/Shanghai",
    conversation_context=[...],
    context_state=ConversationContextState(...),
    active_memory_context=ActiveMemoryContext(...),
)
```

字段含义：

- `new_message`：本次刚进入 conversation 的消息。
- `timezone`：conversation 提供的 IANA 时区名，例如 `Asia/Shanghai`。memory 用它解析“明天”“下周”“小时候”这类相对或模糊时间。
- `conversation_context`：conversation 认为对 memory 有用的近期上下文，不一定是完整历史。
- `context_state`：conversation 当前上下文窗口状态，例如 `context_start_index`、总消息数、活跃消息 id。
- `active_memory_context`：与当前有效上下文相关的近期记忆工作集。它通常由 memory 从缓存或检索结果中填充，conversation 可以不传。

memory 的输入对象必须是中立 DTO，不能要求调用方传入 `conversation.models.Message`。

`timezone` 和具体 UTC offset 不是一回事。conversation 至少应提供时区名；消息自己的 `created_at` 可以携带具体 offset，memory 写入时间记忆时再同时保留两者。

## 4. 活跃记忆工作集

memory 应维护一个轻量的 `ActiveMemoryContext`，用来缓存最近和当前有效上下文相关的记忆。

在这套系统里，`Event` 更接近 topic 或语境单元，不表示每个小事件。具体细节、小事实、小事件由 `Description` 表达。因此 `ActiveMemoryContext.event_memories` 是当前活跃 topic 列表。

它可以包含：

- 当前活跃 topic 相关的 `event_memories`，按最近提及顺序排序。
- 当前话题涉及的 `entity_memories`。
- 当前话题相关的 `property_memories`。
- 其他辅助记忆，例如 session summary 或 retrieval hints。
- `last_refreshed_at_message_id`：这组缓存最近对应到哪条消息。

不需要在 `ActiveMemoryContext` 上维护全局 `topic_summary` 或 `topic_started_at_message_id`。当前活跃上下文的起点默认就是 conversation active context 的第一条消息；每个 event 自己可以携带 summary。

这个工作集不是权威存储，也不是数据库表。它的作用是：

- 喂给 memory candidate extractor，避免多轮都在说同一件事时反复抽取同一条记忆。
- 帮助判断新消息是在延续当前话题，还是已经进入新话题。
- 辅助判断是否应该建议 conversation 压缩旧上下文。
- 减少每轮都做全量检索的成本。

刷新策略建议：

- 当新消息命中已有 event 时，将该 event 移到 `event_memories` 前面，并更新它在 metadata 中的最近提及信息。
- 当新消息开启新话题时，检索或创建对应 event，并放到 `event_memories` 前面。
- 当 memory 写入了新的 event/entity/property 后，把结果并入工作集。
- 当 conversation 执行了 `set_context_start` 或摘要压缩后，刷新工作集。
- 可以设置 event 数量上限、TTL 或最大 message span，避免缓存长期漂移。

当 `event_memories` 积累到一定数量后，memory 可以优先处理长时间未提及的 event：

- 找出冷却 event 覆盖的消息范围。
- 建议对这些范围执行 `summarize_range`。
- 压缩成功后，从 `ActiveMemoryContext` 中移除这些冷却 event。
- 这里的移除只表示退出活跃工作集，不删除长期记忆库里的 event。

如果压缩时当前工作集里只有一个 event，该 event 应继续留在缓存中，因为它仍代表当前活跃话题。其他情况下保留几个 event 先不硬编码，后续根据真实效果调整。

## 5. Turn 输出

memory 返回 `MemoryTurnResult`：

```python
MemoryTurnResult(
    memory_context=[...],
    context_actions=[...],
    created_memories=[...],
    updated_memories=[...],
)
```

字段含义：

- `memory_context`：给 conversation 注入 LLM prompt 的记忆上下文块。
- `context_actions`：建议 conversation 执行的上下文维护动作。
- `created_memories`：本次新建的记忆记录。
- `updated_memories`：本次更新、合并或失效的记忆记录。

第一阶段使用可替换 store 的 memory runtime：active context cache、retriever、reconciler、writer
和 conversation 接线都是真实的。默认 `LLMMemoryExtractor` 会从新消息、近期上下文、时区和
active memory context 中抽取候选记忆；memory runtime 再检索相关旧记忆、生成 write plan，并把
write plan 应用到当前 `MemoryStore`。本地开发可以使用 `InMemoryMemoryStore`；当 conversation
使用 PostgreSQL 后端时，默认会同步使用 `PostgresMemoryStore` 保存当前通用 `MemoryRecord`
信封和 source refs。candidate retrieval 继续读取这个 generic store 给 reconciler 查重、reuse
和 attach；prompt retrieval 在 PostgreSQL 后端默认先通过 `PostgresNormalizedMemoryLookup`
在数据库层筛选 event/description/entity/property 候选，再读取范式化 repository hydrate 成
prompt view，避免把 raw `link`、`time_link` 等机器关系直接放进 prompt。

范式化持久层已经作为独立 repository 起步：`memory/persistence/postgres/` 会创建
`memory_events`、`memory_descriptions`、`memory_entities`、`memory_properties`、
`memory_links`、`memory_time_refs`、`memory_time_links` 和 `memory_sources`。当 conversation 使用
PostgreSQL 后端时，runtime 会通过 `MemoryWriteResultPersistenceSync` 把本轮 write result 中的
`MemoryRecord` 映射成 `PersistentMemoryBundle`，再写入范式化 repository。
`NormalizedMemoryRetriever` 会接收 lookup 命中的 object refs，并从这些表中组装 event/entity
视图：命中 description 会回到 parent event，命中 property 会回到 parent entity；event 自动带
description、related entity 和 time；entity 自动带 property 和 related event。source 和 link
仍可追溯，但默认不作为 prompt 可见文本。

Extractor contract 当前采用聚合候选输出：

- extractor 只负责尽可能提取候选事实，不负责检索已有记忆、不去重、不合并、不判定更新或最终写入。
- `active_memory_context` 在 extractor 阶段只用于理解指代和语义，不用于压制候选输出。
- LLM 输出 `event_candidates[]` 和 `entity_candidates[]`，而不是直接输出底层 `event`、`description`、`link`、`time_link`。
- `event_candidate` 表示 durable topic、episode、plan、appointment、story beat 或更大的语境单元，必须至少包含一个 `description`。
- `description` 表示事件里的具体细节、观察或小事实，不能孤立存在。
- `entity_candidate` 表示人物、地点、物品、概念、故事实体等，`property` 必须嵌套在所属 entity 下。
- 用户也可以作为普通 entity 候选输出，后续 reconciliation 再和系统用户实体合并。
- `time` 嵌套在 event、description 或 property 上；normalizer 再拆成底层 `time_ref` 和 `time_link`。

`time_ref.metadata` 必须包含稳定字段：`raw_text`、`time_kind`、`timeline_kind`、`certainty`、`anchor_timezone`、`anchor_utc_offset`。不同 `time_kind` 还需要额外字段：`exact` 需要 `resolved_start` 和 `granularity`；`relative` 需要 `anchor_message_id`、`resolved_start` 和 `granularity`；`vague` 需要 `description`；`duration` 需要 `duration_text`；`recurring` 需要 `recurrence_text`。如果 event 没有显式或可推断的事件时间，但仍值得抽取，应以消息提及时间建立 `time_ref` 并用 `time_role=mentioned_at` 连接。

## 6. 上下文压缩

上下文压缩由 memory 决策，由 conversation 执行。

memory 可以返回这些动作：

- `summarize_range`：建议把一段旧消息压缩成摘要。
- `set_context_start`：建议把 LLM 上下文起点移动到某条消息。
- `pin_messages`：建议保留某些关键消息不被普通窗口策略丢弃。

conversation 收到动作后可以选择：

- 立即执行。
- 延迟执行。
- 因权限、状态或并发原因拒绝执行。

这个边界很重要：memory 可以指定策略，但不越权写 conversation 表。

`ActiveMemoryContext` 可以参与压缩判断：

- 如果新消息仍然命中 `event_memories` 前部的 event，通常说明话题延续，不急着压缩最新上下文。
- 如果新消息长期不再命中某些 event，且引入了新实体或新目标，可以认为旧 event 冷却，适合建议压缩它覆盖的消息范围。
- 如果 `event_memories` 已经超过阈值，可以优先压缩长时间未提及的 event。
- 如果当前活跃上下文已经过长，即使还没有明显话题切换，也可以提前建议压缩旧消息范围。

压缩后，conversation 构造下一次 LLM prompt 时，除了携带仍在窗口内的原始上下文，还应在原始上下文开头附带刚刚压缩得到的新鲜摘要。这样模型不会因为移动上下文起点而丢掉刚被压缩的语境。

## 7. 推荐处理顺序

一次用户消息的推荐流程：

1. conversation 保存 user message。
2. conversation 读取近期消息、当前 context state 和用户时区。
3. conversation 调用 `memory.process_turn(...)`。
4. memory 加载或刷新 `ActiveMemoryContext`。
5. memory 把新消息、conversation context、active memory context 一起交给 extractor。
6. memory 抽取聚合候选事实，并拆分成当前 runtime 可处理的 `MemoryRecord`。
7. memory 用候选记忆检索相关旧记忆，得到 direct/expanded 相关记录。
8. memory reconciler 根据候选和相关旧记忆生成 `MemoryWritePlan`。
9. memory writer 把 write plan 应用到当前 `MemoryStore`。
10. 如果配置了 persistence sync，memory 把 write result 同步写入范式化持久层。
11. memory 用新建、挂载和复用的记忆刷新 `ActiveMemoryContext`。
12. memory 返回 `memory_context` 和 `context_actions`。
13. conversation 执行允许的 `context_actions`。
14. 如果刚执行了摘要压缩，conversation 将新摘要放在原始 conversation context 开头。
15. conversation 构造 LLM prompt：system prompt、压缩摘要、conversation context、memory context。
16. conversation 调用 LLM。
17. conversation 保存 assistant message。
18. conversation 可选择再次调用 memory，让 assistant message 也进入记忆处理。

第 18 步不是强制的。第一阶段可以只处理用户消息。

## 8. 失败策略

memory 失败不应该阻断基础对话能力。

建议默认策略：

- memory 抽取失败：记录错误，conversation 继续调用 LLM。
- memory 检索失败：不注入记忆上下文，conversation 继续调用 LLM。
- context action 执行失败：跳过该动作，保留原上下文窗口。

如果未来某些场景强依赖记忆，可以在调用方显式开启严格模式。

## 9. 当前接口位置

当前已经建立接口，并提供进程内和 PostgreSQL store：

- `memory/models.py`：中立数据契约。
- `memory/interfaces.py`：memory 系统、抽取、存储、检索、上下文策略接口。
- `memory/system.py`：`InMemoryMemorySystem`，组合抽取、候选检索、reconciliation、
  write plan application、活跃缓存、prompt 检索和上下文策略。
- `memory/config.py`：memory runtime 配置，例如是否启用 LLM 抽取、抽取模型、抽取温度和上下文条数。
- `memory/storage/in_memory.py`：进程内记忆记录 store，不持久化。
- `memory/storage/ids.py`：不同记忆类型的 id 前缀和 id 生成。
- `memory/storage/postgres/`：PostgreSQL 版 memory store，当前保存通用 `MemoryRecord`
  和 `MemorySourceRef`；不是最终范式化记忆表的完整 repository。
- `memory/context/cache.py`：进程内 `ActiveMemoryContext` 缓存。
- `memory/context/policy.py`：暂不生成压缩动作的 policy。
- `memory/extraction/pipeline.py`：最小 LLM 抽取流程，负责调用模型、解析聚合响应并规范化为 `MemoryRecord`。
- `memory/extraction/llm.py`：LLM 调用适配层，只返回模型原始响应文本。
- `memory/extraction/prompt.py`：抽取 prompt 构造。
- `memory/extraction/parser.py`：聚合候选 JSON 响应解析。
- `memory/extraction/normalizer.py`：把聚合候选拆分为 `MemoryRecord`。
- `memory/extraction/validation.py`：聚合候选校验，包括 event 必须有 description、时间字段契约等。
- `memory/persistence/models.py`：范式化持久记忆 DTO。
- `memory/persistence/interfaces.py`：范式化持久记忆 repository 协议。
- `memory/persistence/runtime.py`：把 `MemoryWriteResult` 中的通用 `MemoryRecord` 映射成
  `PersistentMemoryBundle`，并同步写入范式化 repository。
- `memory/persistence/postgres/`：PostgreSQL 范式化持久记忆 repository、lookup 和 schema。
- `memory/extraction/noop.py`：不抽取候选记忆的 extractor，用于测试或临时关闭。
- `memory/retrieval/lookup.py`：normalized retrieval 的 lookup DTO/Protocol，以及非 Postgres
  repository 的 fallback lookup。
- `memory/retrieval/simple.py`：基于 scope 和简单文本匹配的 store 检索与 prompt context 渲染。
- `memory/retrieval/normalized.py`：基于范式化 repository 的 prompt retrieval；渲染 event/entity
  视图，并隐藏 raw link/time_link 等低层关系对象。
- `memory/retrieval/candidate.py`：面向 reconciliation 的候选检索，输入抽取候选，返回相关旧记忆、分数、命中原因和 direct/expanded 标记。结果同时提供全局 `records` 和按候选分组的 `groups`。第一版使用确定性规则，并严格只做一跳 link/time_link 扩展，不调用 LLM 或向量库。
- `memory/reconciliation/models.py`：reconciliation 请求、证据、操作和 write plan DTO。write plan 只描述 create/reuse/attach/ignore/flag_conflict，不直接修改 store。
- `memory/reconciliation/interfaces.py`：`MemoryReconciler` 协议，后续 LLM reconciler 和确定性 reconciler 使用同一接口。
- `memory/reconciliation/deterministic.py`：确定性 baseline reconciler，基于 candidate retriever 的 grouped result 生成最小 write plan。
- `memory/writing/models.py`：write request、write result 和失败 DTO。
- `memory/writing/interfaces.py`：`MemoryWritePlanApplier` 协议，负责把 write plan 应用到具体 store。
- `memory/writing/in_memory.py`：当前通用 write plan applier，处理 create/reuse/attach/ignore/flag_conflict，
  并维护 candidate id 到最终 record id 的映射；名字保留为历史原因，但依赖的是 `MemoryStore`
  协议，不再绑定进程内 store。
- `memory/noop.py`：完全无操作实现，用于测试或临时关闭 memory。
- `memory/__init__.py`：公共导出。

后续实现可以继续拆分：

- `memory/extraction/pipeline.py`：基于共享 `llm/` 的候选记忆抽取流程。
- `memory/retrieval/vector.py`：在 normalized retrieval 之下增加 embedding/ranking。
- `memory/context/policy.py`：真实上下文压缩策略。
