# 数据库设计文档：记忆模型

本文档描述一套面向记忆系统的数据库设计。目标是把「发生过的事」「事件中的细节」「长期稳定事实」「实体之间的关系」分层存储，并且让每一条记忆都能追溯到当前会话系统中的 `messages.id`，以及由消息切分出的 `message_sections.id`。

## 1. 设计目标

这套模型的核心原则是：

- `Event` 负责记录发生过的事。
- `Description` 负责记录事件中的可拆分信息点。
- `Entity` 负责记录被描述的对象。
- `Property` 负责记录实体的长期或半长期事实。
- `Link` 负责连接任意对象，并解释它们为什么有关。
- 所有可入库的记忆都必须能追溯到至少一个 `message_sections.id`。

这样可以同时支持：

- 一个 `Event` 拥有多个 `Description`。
- 不同 `Description` 之间跨事件连接。
- `Property` 来源于 `Event`、`Description` 和 `message_sections`。
- 一个 `Entity` 被多个 `Property` 描述。
- 记忆的来源、推导过程和失效过程都可审计。

## 2. 总体分层

建议把数据分成 5 层：

1. `messages / message_sections`：原始来源层。
2. `Event`：大事件层。
3. `Description`：事件细节层。
4. `Entity`：实体层。
5. `Property`：知识层。

另外增加一层统一关系表：

- `Link`：用于连接任意对象。

以及一层语义时间：

- `MemoryTimeRef`：保存“前几周”“小时候”“很久很久以前”等时间表达及解析结果。
- `MemoryTimeLink`：把时间表达连接到事件、属性、实体、描述或消息片段，并说明时间角色。

以及一层检索索引：

- `MemoryEmbedding`：用于后续向量检索和上下文构建。

可以把它理解为：

- `Event` 是故事层。
- `Description` 是细节层。
- `Entity / Property` 是知识层。
- `Link` 是关联层。
- `message_sections` 是证据层。
- `MemoryTimeRef / MemoryTimeLink` 是时间解释层。
- `MemoryEmbedding` 是检索层。

## 3. 原始来源层

当前项目已经有 `users`、`sessions`、`messages` 三张基础会话表，所以记忆系统第一阶段不再新增独立 `RawMessage` 表。原始消息直接复用 `messages.id`，记忆系统只新增 `message_sections` 表，用来保存从一条消息中切分出来的可引用片段。

这样做可以避免出现两套消息概念：

- `messages.id`：完整原始消息。
- `message_sections.id`：完整消息中的片段，用作记忆证据。
- `message_sections.message_id`：外键指向 `messages(id)`。
- `message_sections.session_id`、`message_sections.user_id`：冗余作用域字段，便于过滤和权限控制。

不要再使用含糊的 `raw_msg_id` 或 `conversation_id`。当前系统中等价概念分别是 `message_id` 和 `session_id`。

### 3.2 强制约束

建议约束：

- `Event` 必须至少关联一个 `message_section_id`。
- `Description` 必须至少关联一个 `message_section_id`。
- `Property` 必须至少关联一个来源引用，来源可以是 `message_section`、`event` 或 `description`，但最终仍要能追溯到 `message_sections.id`。
- `Link` 也应保留来源引用，便于解释为什么建立该连接。

## 4. Event 设计

`Event` 表示一个可被标题概括的“大事件”。它不应塞入太多细节，细节由 `Description` 承担。

示例：

```json
{
  "id": "event_001",
  "title": "早上电车撞鹿导致列车延误",
  "summary": "早上乘坐的电车因为撞到鹿而发生延误。",
  "event_type": "incident",
  "user_id": "usr_001",
  "session_id": "ses_001",
  "status": "active",
  "source_message_section_ids": ["msgsec_001"],
  "created_at": "2026-05-08T08:31:00+09:00",
  "updated_at": "2026-05-08T08:31:00+09:00",
  "confidence": "high",
  "importance": "medium",
  "metadata": {
    "location": null
  }
}
```

### 4.1 推荐字段

| 字段 | 作用 |
| --- | --- |
| `title` | 高度概括，适合检索和展示 |
| `summary` | 比标题更详细的摘要 |
| `event_type` | 事件类型，例如 `incident`、`plan`、`conversation`、`preference_change` |
| `created_at` | 记忆进入系统的时间 |
| `updated_at` | 最近更新时间 |
| `confidence` | 置信度，建议只用粗粒度 |
| `importance` | 重要程度，用于长期保留 |

### 4.2 Event 建议状态

- `active`
- `archived`
- `invalidated`
- `expired`
- `merged`
- `deleted`

## 5. Description 设计

`Description` 用于承载事件中的可拆分信息点。

一个 `Event` 可以有多个 `Description`，例如：

- 电车撞到的是鹿。
- 电车是早上的班次。
- 这件事导致列车延误。
- 当地似乎经常发生鹿闯入轨道的事情。
- 用户联想到日本乡下电车可能经常遇到动物。

示例：

```json
{
  "id": "desc_001",
  "event_id": "event_001",
  "user_id": "usr_001",
  "session_id": "ses_001",
  "content": "撞到的是鹿。",
  "description_type": "detail",
  "source_message_section_ids": ["msgsec_001"],
  "created_at": "2026-05-08T08:31:10+09:00",
  "updated_at": "2026-05-08T08:31:10+09:00",
  "confidence": "high",
  "importance": "low",
  "metadata": {
    "extracted_by": "llm",
    "normalized": false
  }
}
```

另一个示例：

```json
{
  "id": "desc_002",
  "event_id": "event_001",
  "user_id": "usr_001",
  "session_id": "ses_001",
  "content": "这次电车延误发生在早上。",
  "description_type": "time_detail",
  "source_message_section_ids": ["msgsec_001"],
  "created_at": "2026-05-08T08:31:12+09:00",
  "updated_at": "2026-05-08T08:31:12+09:00",
  "confidence": "medium",
  "importance": "low"
}
```

### 5.1 建议类型

- `detail`
- `cause`
- `result`
- `time_detail`
- `location_detail`
- `frequency`
- `emotion`
- `inference`
- `association`
- `correction`
- `contradiction`

其中 `inference`、`association` 的置信度通常不宜过高。

### 5.2 Description 跨事件连接

`Description` 可以跨 `Event` 连接，但不建议把这种关系硬编码在 `Description` 本身。更稳妥的做法是统一交给 `Link` 表表达。

例如：

```json
{
  "id": "link_001",
  "from_type": "description",
  "from_id": "desc_004",
  "to_type": "description",
  "to_id": "desc_009",
  "relation_type": "similar_context",
  "reason": "两条描述都涉及动物闯入铁路导致交通异常，可能属于同类事件。",
  "created_at": "2026-05-08T08:40:00+09:00",
  "updated_at": "2026-05-08T08:40:00+09:00",
  "confidence": "medium",
  "metadata": {
    "link_created_by": "llm",
    "bidirectional": true
  }
}
```

### 5.3 建议关系类型

- `supports`
- `contradicts`
- `elaborates`
- `causes`
- `caused_by`
- `similar_context`
- `same_event`
- `same_entity`
- `temporal_sequence`
- `generalizes`
- `specializes`
- `associated_with`
- `corrects`

## 6. Entity 设计

`Entity` 表示被描述的对象，例如：

- 用户
- 苹果
- 鹿
- 电车
- 电车轨道
- 某条线路
- 日本乡下铁路

示例：

```json
{
  "id": "entity_001",
  "user_id": null,
  "session_id": null,
  "scope": "global",
  "name": "鹿",
  "entity_type": "animal",
  "identity_summary": "鹿这一类动物的整体概念。",
  "aliases": ["deer"],
  "created_at": "2026-05-08T08:31:30+09:00",
  "updated_at": "2026-05-08T08:31:30+09:00",
  "metadata": {}
}
```

用户实体示例：

```json
{
  "id": "entity_user_usr_001",
  "user_id": "usr_001",
  "session_id": null,
  "scope": "user",
  "name": "当前用户",
  "entity_type": "person",
  "identity_summary": "当前对话系统中的这个用户本人。",
  "aliases": ["我", "user"],
  "created_at": "2026-05-08T08:31:30+09:00",
  "updated_at": "2026-05-08T08:31:30+09:00"
}
```

### 6.1 Entity 建议字段

- `name`
- `entity_type`
- `user_id`
- `session_id`
- `scope`
- `identity_summary`
- `aliases`
- `metadata`

`Entity` 本身尽量保持稳定，不要塞太多会频繁变化的事实。用户相关实体必须带作用域，避免不同用户的“我”“我的朋友”“我的公司”等实体互相串记忆。

## 7. Property 设计

`Property` 用于描述实体的长期或半长期事实。

例如：

- 我喜欢苹果。
- 鹿会闯入电车轨道。
- 用户经常关注铁路延误原因。
- 某地区的电车可能经常因为鹿而延误。

示例：

```json
{
  "id": "prop_001",
  "entity_id": "entity_user_usr_001",
  "user_id": "usr_001",
  "session_id": "ses_001",
  "property_name": "likes",
  "property_value": "苹果",
  "value_type": "text",
  "value_json": null,
  "property_text": "用户喜欢苹果。",
  "property_type": "preference",
  "source_refs": [
    {
      "source_type": "message_section",
      "source_id": "msgsec_010"
    }
  ],
  "created_at": "2026-05-08T09:00:00+09:00",
  "updated_at": "2026-05-08T09:00:00+09:00",
  "confidence": "high",
  "stability": "stable",
  "importance": "medium",
  "status": "active",
  "metadata": {
    "extracted_by": "llm"
  }
}
```

鹿的属性示例：

```json
{
  "id": "prop_002",
  "entity_id": "entity_001",
  "user_id": null,
  "session_id": "ses_001",
  "property_name": "may_enter",
  "property_value": "电车轨道",
  "value_type": "entity_ref",
  "value_json": {"target_entity_id": "entity_track"},
  "property_text": "鹿可能会闯入电车轨道。",
  "property_type": "general_fact",
  "source_refs": [
    {
      "source_type": "event",
      "source_id": "event_001"
    },
    {
      "source_type": "description",
      "source_id": "desc_004"
    },
    {
      "source_type": "message_section",
      "source_id": "msgsec_001"
    }
  ],
  "created_at": "2026-05-08T08:35:00+09:00",
  "updated_at": "2026-05-08T08:35:00+09:00",
  "confidence": "medium",
  "stability": "semi_stable",
  "importance": "low",
  "status": "active"
}
```

### 7.1 Property 类型建议

- `preference`
- `habit`
- `skill`
- `identity`
- `general_fact`
- `location_fact`
- `relationship`
- `constraint`
- `goal`
- `belief`
- `temporary_state`

### 7.2 Property 生命周期

当旧事实被新事实推翻时，不建议直接覆盖。更好的方式是：

- 旧 `Property` 标记为 `invalidated`
- 新增一条 `memory_time_refs`，并通过 `memory_time_links` 用 `valid_to` 或 `observed_at` 角色描述失效时间
- 新建新的 `Property`
- 用 `Link` 把两者连接起来，说明是 `corrects` 或 `contradicts`

示例：

```json
{
  "id": "prop_001",
  "property_text": "用户喜欢苹果。",
  "status": "invalidated",
  "invalidated_by": "prop_003"
}
```

## 8. 时间字段设计

时间分成两类：

1. 系统生命周期时间：数据库或系统行为产生的时间，例如 `created_at`、`updated_at`、`deleted_at`。这些字段保留在各自表里。
2. 语义时间：用户表达、故事文本或记忆内容中的时间，例如“前几周”“小时候”“持续了一两年”“很久很久以前”。这些时间单独进入 `memory_time_refs`，再通过 `memory_time_links` 连接到 `Event`、`Description`、`Property`、`Link` 或 `Entity`。

不要把语义时间直接塞进每张表的 `occurred_at`、`valid_from`、`valid_to`。这些表达经常是模糊的、相对的、持续性的，甚至不属于现实世界时间轴。

语义时间不是各主表上的 JSON 字段。真正落库时应拆成 `memory_time_refs` 和 `memory_time_links`；需要返回给 API 或 LLM 时，可以在 service 层聚合成带时间信息的视图。

### 8.1 系统时间

系统时间建议保留：

| 字段 | 含义 |
| --- | --- |
| `created_at` | 系统什么时候创建这条记录 |
| `updated_at` | 系统什么时候最后更新这条记录 |
| `deleted_at` | 系统什么时候软删除这条记录 |

系统时间写入时也必须带时区。PostgreSQL 中可以使用 `TIMESTAMPTZ` 保存真实瞬间；如果需要按“当时记录时区”返回，还应在请求上下文或审计信息中保留时区名。

### 8.2 语义时间

语义时间由 `memory_time_refs` 表保存原始表达和解析结果。它支持：

- 精确时间：`2026-05-09 20:00`
- 模糊时间：`前几周`、`小时候`、`最近`
- 持续时间：`持续了一两年`
- 频率时间：`每周`、`经常`
- 非现实/叙事时间：`很久很久以前`、`故事开头`、`第二纪元`

语义时间再通过 `memory_time_links.time_role` 表达它对某个记忆对象的意义，例如：

- `occurred_at`：事件发生时间
- `observed_at`：用户说出或系统观察到该信息的时间
- `valid_from`：事实开始有效
- `valid_to`：事实不再有效
- `duration`：持续时间
- `deadline`：截止时间
- `scheduled_for`：计划时间
- `life_stage`：人生阶段
- `recurrence`：频率
- `narrative_time`：叙事时间

### 8.3 时区

真实世界时间写入时必须带时区，不能写裸时间。查询返回时，应返回：

- UTC 标准时间。
- 按记录时区还原后的本地时间。
- IANA 时区名，例如 `Asia/Shanghai`。
- 当时 UTC offset，例如 `+08:00`。

`timezone` 和 `utc_offset` 不是一回事：

- `timezone` 是一套时区规则，例如 `Asia/Shanghai`、`America/New_York`。
- `utc_offset` 是某一具体时刻相对 UTC 的偏移，例如 `+08:00`、`-05:00`、`-04:00`。

例如 `America/New_York` 在冬天可能是 `-05:00`，夏令时可能是 `-04:00`。同时保存两者可以在未来时区规则变化时仍保留当时记录的解释。

### 8.4 非现实时间

不是所有时间都能或都应该规范化成现实时间。比如：

- `很久很久以前`
- `故事开头`
- `第二纪元`
- `梦里那天`

这类时间应设置 `time_domain = 'narrative'` 或 `time_domain = 'fictional'`，保留 `raw_text` 和 `narrative_position`，不要强行写入 `normalized_start` / `normalized_end`。

### 8.5 示例

“我以前喜欢苹果，但现在不喜欢了。”

可以把旧 `Property` 标记为 `invalidated`，新建新的 `Property`，并用 `memory_time_refs` + `memory_time_links` 描述“以前”和“现在”对应的语义时间。

## 9. 置信度设计

建议只保留 3 个等级：

- `high`
- `medium`
- `low`

### 9.1 含义

| 置信度 | 含义 |
| --- | --- |
| `high` | 用户明确说了，或来源很直接 |
| `medium` | 合理推断，但不是用户直接表达 |
| `low` | 联想、猜测、弱相关信息 |

### 9.2 建议

- 用户明确说出的事实，通常记为 `high`。
- 由上下文推断出的事实，通常记为 `medium`。
- 联想、猜测、弱相关内容，通常记为 `low`。

## 10. 状态设计

建议 `Event`、`Description`、`Property`、`Link` 都具备统一状态字段：

- `active`
- `archived`
- `invalidated`
- `expired`
- `merged`
- `deleted`

这样比物理删除更适合记忆系统，因为可以保留：

- 为什么这条记忆失效
- 谁覆盖了它
- 它曾经从哪些来源来

## 11. PostgreSQL 落地表设计

第一阶段建议只在当前 `users`、`sessions`、`messages` 之上新增记忆层表，不替换现有会话表。系统生命周期时间使用 `TIMESTAMPTZ`，结构化字段使用 `JSONB`。语义时间统一写入 `memory_time_refs`，并通过 `memory_time_links` 连接到各类记忆对象。

### 11.1 `message_sections`

```sql
CREATE TABLE message_sections (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
    role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
    section_index INTEGER NOT NULL,
    section_text TEXT NOT NULL,
    start_char INTEGER,
    end_char INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (message_id, section_index)
);
```

### 11.2 `memory_events`

```sql
CREATE TABLE memory_events (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    summary TEXT,
    event_type TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    merged_into_id TEXT REFERENCES memory_events(id) ON DELETE SET NULL,
    deleted_at TIMESTAMPTZ,
    deleted_reason TEXT,
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    importance TEXT CHECK (importance IN ('high', 'medium', 'low')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

### 11.3 `memory_descriptions`

```sql
CREATE TABLE memory_descriptions (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL REFERENCES memory_events(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    content TEXT NOT NULL,
    description_type TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    merged_into_id TEXT REFERENCES memory_descriptions(id) ON DELETE SET NULL,
    deleted_at TIMESTAMPTZ,
    deleted_reason TEXT,
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    importance TEXT CHECK (importance IN ('high', 'medium', 'low')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

### 11.4 `memory_entities`

```sql
CREATE TABLE memory_entities (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
    scope TEXT NOT NULL DEFAULT 'user' CHECK (scope IN ('global', 'user', 'session')),
    name TEXT NOT NULL,
    entity_type TEXT,
    identity_summary TEXT,
    aliases JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

### 11.5 `memory_properties`

```sql
CREATE TABLE memory_properties (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES memory_entities(id) ON DELETE CASCADE,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    property_name TEXT NOT NULL,
    property_value TEXT,
    value_type TEXT DEFAULT 'text',
    value_json JSONB,
    property_text TEXT NOT NULL,
    property_type TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
    stability TEXT CHECK (stability IN ('stable', 'semi_stable', 'temporary')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    invalidated_by TEXT REFERENCES memory_properties(id) ON DELETE SET NULL,
    merged_into_id TEXT REFERENCES memory_properties(id) ON DELETE SET NULL,
    deleted_at TIMESTAMPTZ,
    deleted_reason TEXT,
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    importance TEXT CHECK (importance IN ('high', 'medium', 'low')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

### 11.6 `memory_links`

`memory_links` 保留灵活连接能力。由于 `from_id`、`to_id` 是多态引用，数据库不能直接对它们建立真实外键，因此必须在 service 层校验目标对象存在。

```sql
CREATE TABLE memory_links (
    id TEXT PRIMARY KEY,
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    from_type TEXT NOT NULL CHECK (from_type IN ('event', 'description', 'entity', 'property')),
    from_id TEXT NOT NULL,
    to_type TEXT NOT NULL CHECK (to_type IN ('event', 'description', 'entity', 'property')),
    to_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    reason TEXT,
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived', 'invalidated', 'expired', 'merged', 'deleted')),
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    deleted_reason TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (from_type, from_id, to_type, to_id, relation_type)
);
```

### 11.7 `memory_sources`

统一来源表用来表达“某个记忆对象由哪些消息片段、事件或描述支持”。其中 `message_section_id` 是强外键，`source_type/source_id` 用于记录额外推导来源。

```sql
CREATE TABLE memory_sources (
    id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL CHECK (memory_type IN ('event', 'description', 'property', 'link')),
    memory_id TEXT NOT NULL,
    message_section_id TEXT REFERENCES message_sections(id) ON DELETE CASCADE,
    source_type TEXT CHECK (source_type IN ('message_section', 'event', 'description', 'property', 'link')),
    source_id TEXT,
    evidence_text TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    CHECK (message_section_id IS NOT NULL OR (source_type IS NOT NULL AND source_id IS NOT NULL))
);
```

### 11.8 `memory_time_refs`

`memory_time_refs` 保存语义时间表达本身。真实时间必须记录时区；非现实时间保留叙事位置，不强行规范化。

```sql
CREATE TABLE memory_time_refs (
    id TEXT PRIMARY KEY,
    raw_text TEXT,
    time_domain TEXT NOT NULL DEFAULT 'real_world'
        CHECK (time_domain IN ('real_world', 'narrative', 'fictional', 'life_stage', 'unknown')),
    time_kind TEXT NOT NULL
        CHECK (time_kind IN ('instant', 'range', 'duration', 'recurrence', 'relative', 'vague')),
    certainty TEXT NOT NULL DEFAULT 'unknown'
        CHECK (certainty IN ('exact', 'approximate', 'vague', 'unknown')),

    anchor_at TIMESTAMPTZ,
    anchor_timezone TEXT,
    anchor_utc_offset TEXT,

    normalized_start TIMESTAMPTZ,
    normalized_end TIMESTAMPTZ,
    normalized_timezone TEXT,
    normalized_utc_offset TEXT,

    duration_min NUMERIC,
    duration_max NUMERIC,
    duration_unit TEXT,
    recurrence_rule TEXT,

    calendar_system TEXT DEFAULT 'gregorian',
    narrative_position TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);
```

字段说明：

- `anchor_at` 是理解相对时间时使用的锚点，通常是用户消息的 `created_at` 或系统处理这句话的时间。
- `anchor_timezone` 保存 IANA 时区名，例如 `Asia/Shanghai`、`America/New_York`。
- `anchor_utc_offset` 保存记录当时的实际偏移，例如 `+08:00`、`-05:00`。
- `normalized_start` / `normalized_end` 是在真实世界时间轴上解析出的范围，无法解析或不是现实时间时留空。
- `normalized_timezone` / `normalized_utc_offset` 用于返回规范化结果时，还原当时记录时区下的本地时间。
- `time_domain = 'narrative'` 或 `time_domain = 'fictional'` 时，可以只填写 `raw_text`、`narrative_position` 和 `metadata`，不填写 `normalized_start` / `normalized_end`。

### 11.9 `memory_time_links`

`memory_time_links` 负责把时间表达挂到任意记忆对象上，并说明这段时间的角色。

```sql
CREATE TABLE memory_time_links (
    id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL
        CHECK (memory_type IN ('event', 'description', 'entity', 'property', 'link', 'message_section')),
    memory_id TEXT NOT NULL,
    time_ref_id TEXT NOT NULL REFERENCES memory_time_refs(id) ON DELETE CASCADE,
    time_role TEXT NOT NULL
        CHECK (time_role IN (
            'occurred_at',
            'observed_at',
            'valid_from',
            'valid_to',
            'duration',
            'deadline',
            'scheduled_for',
            'life_stage',
            'recurrence',
            'narrative_time'
        )),
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (memory_type, memory_id, time_ref_id, time_role)
);
```

### 11.10 `memory_embeddings`

第一阶段可以先存 embedding 元信息和向量文本占位。真正启用向量检索时，建议安装 `pgvector`，把 `embedding` 改为 `vector(n)`。

```sql
CREATE TABLE memory_embeddings (
    id TEXT PRIMARY KEY,
    memory_type TEXT NOT NULL CHECK (memory_type IN ('event', 'description', 'entity', 'property', 'link', 'message_section')),
    memory_id TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    embedding_dimensions INTEGER,
    embedding JSONB,
    content_hash TEXT NOT NULL,
    embedded_text TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_accessed_at TIMESTAMPTZ,
    access_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (memory_type, memory_id, embedding_model, content_hash)
);
```

## 12. 推荐约束

建议补充以下约束或索引：

- `message_sections(message_id, section_index)` 设置唯一约束。
- `message_sections(session_id, created_at)`、`message_sections(user_id, created_at)` 建索引。
- `memory_events(user_id, event_type, status)` 建索引。
- `memory_events(user_id, status, importance)` 建索引。
- `memory_descriptions(event_id)`、`memory_descriptions(user_id, status)` 建索引。
- `memory_entities(scope, user_id)`、`memory_entities(scope, session_id)` 建索引，用于限定候选实体范围。
- `memory_properties(entity_id, property_name, status)` 建复合索引。
- `memory_properties(user_id, status, importance)` 建索引。
- `memory_links(from_type, from_id)` 和 `memory_links(to_type, to_id)` 建索引。
- `memory_sources(memory_type, memory_id)` 和 `memory_sources(message_section_id)` 建索引。
- `memory_time_refs(time_domain, time_kind, certainty)` 建索引。
- `memory_time_refs(normalized_start, normalized_end)` 建索引，用于真实世界时间范围过滤。
- `memory_time_links(memory_type, memory_id, time_role)` 和 `memory_time_links(time_ref_id)` 建索引。
- `memory_embeddings(memory_type, memory_id)` 建索引。

`memory_sources`、`memory_links`、`memory_time_links`、`memory_embeddings` 这类多态引用表不能完全依赖数据库外键保证目标存在，必须在 repository/service 层做引用检查。需要强一致时，可以额外增加 `memory_objects` 注册表，把所有可引用对象统一登记后再建立外键。

## 13. 图数据库映射

如果使用 Neo4j，可以映射为：

- `(:Message)`
- `(:MessageSection)`
- `(:Event)`
- `(:Description)`
- `(:Entity)`
- `(:Property)`
- `(:TimeRef)`

关系可以映射为：

- `(:Message)-[:HAS_SECTION]->(:MessageSection)`
- `(:Event)-[:HAS_DESCRIPTION]->(:Description)`
- `(:Event)-[:SUPPORTED_BY]->(:MessageSection)`
- `(:Description)-[:SUPPORTED_BY]->(:MessageSection)`
- `(:Property)-[:SUPPORTED_BY]->(:MessageSection)`
- `(:Property)-[:DESCRIBES]->(:Entity)`
- `(:Description)-[:MENTIONS]->(:Entity)`
- `(:Event)-[:MENTIONS]->(:Entity)`
- `(:Description)-[:RELATED_TO {relation_type, reason, confidence, created_at}]->(:Description)`
- `(:Property)-[:DERIVED_FROM]->(:Event)`
- `(:Property)-[:DERIVED_FROM]->(:Description)`
- `(:Event)-[:HAS_TIME {time_role, confidence}]->(:TimeRef)`
- `(:Description)-[:HAS_TIME {time_role, confidence}]->(:TimeRef)`
- `(:Property)-[:HAS_TIME {time_role, confidence}]->(:TimeRef)`
- `(:Entity)-[:HAS_TIME {time_role, confidence}]->(:TimeRef)`

图数据库更适合：

- 查找和“鹿闯入轨道”相关的所有事件
- 查找某个用户偏好的来源
- 查找两个事件之间为什么被系统认为有关
- 查找某个 `Property` 是从哪些 `Event` 和 `Description` 推出来的

关系数据库更适合：

- 稳定存储
- 事务更新
- 状态管理
- 时间过滤
- 语义合并审计

## 14. 一条完整示例

用户原话：

> 早上电车撞鹿导致列车延误。听说这种事在那边经常发生，鹿会闯进轨道。

### 14.1 MessageSection

```json
[
  {
    "id": "msgsec_001",
    "message_id": "msg_001",
    "session_id": "ses_001",
    "user_id": "usr_001",
    "section_index": 0,
    "section_text": "早上电车撞鹿导致列车延误。",
    "created_at": "2026-05-08T08:30:00+09:00"
  },
  {
    "id": "msgsec_002",
    "message_id": "msg_001",
    "session_id": "ses_001",
    "user_id": "usr_001",
    "section_index": 1,
    "section_text": "听说这种事在那边经常发生，鹿会闯进轨道。",
    "created_at": "2026-05-08T08:30:00+09:00"
  }
]
```

### 14.2 Event

```json
{
  "id": "event_001",
  "title": "早上电车撞鹿导致列车延误",
  "summary": "早上的电车因为撞到鹿而发生延误。",
  "event_type": "incident",
  "user_id": "usr_001",
  "session_id": "ses_001",
  "status": "active",
  "created_at": "2026-05-08T08:31:00+09:00",
  "updated_at": "2026-05-08T08:31:00+09:00",
  "confidence": "high",
  "importance": "medium"
}
```

### 14.3 Descriptions

```json
[
  {
    "id": "desc_001",
    "event_id": "event_001",
    "user_id": "usr_001",
    "session_id": "ses_001",
    "content": "电车撞到的是鹿。",
    "description_type": "detail",
    "source_message_section_ids": ["msgsec_001"],
    "confidence": "high"
  },
  {
    "id": "desc_002",
    "event_id": "event_001",
    "user_id": "usr_001",
    "session_id": "ses_001",
    "content": "这件事导致列车延误。",
    "description_type": "result",
    "source_message_section_ids": ["msgsec_001"],
    "confidence": "high"
  },
  {
    "id": "desc_003",
    "event_id": "event_001",
    "user_id": "usr_001",
    "session_id": "ses_001",
    "content": "这种鹿闯入轨道导致交通异常的事情在当地可能经常发生。",
    "description_type": "frequency",
    "source_message_section_ids": ["msgsec_002"],
    "confidence": "medium"
  }
]
```

### 14.4 Entities

```json
[
  {
    "id": "entity_deer",
    "scope": "global",
    "user_id": null,
    "session_id": null,
    "name": "鹿",
    "entity_type": "animal",
    "identity_summary": "鹿这一类动物的整体概念。"
  },
  {
    "id": "entity_train",
    "scope": "global",
    "user_id": null,
    "session_id": null,
    "name": "电车",
    "entity_type": "transport",
    "identity_summary": "用于载客或运输的铁路交通工具。"
  },
  {
    "id": "entity_track",
    "scope": "global",
    "user_id": null,
    "session_id": null,
    "name": "轨道",
    "entity_type": "place",
    "identity_summary": "电车或列车行驶的铁路轨道。"
  }
]
```

### 14.5 Property

```json
[
  {
    "id": "prop_001",
    "entity_id": "entity_deer",
    "user_id": null,
    "session_id": "ses_001",
    "property_name": "may_enter",
    "property_value": "轨道",
    "value_type": "entity_ref",
    "value_json": {"target_entity_id": "entity_track"},
    "property_text": "鹿可能会闯入电车轨道。",
    "property_type": "general_fact",
    "source_refs": [
      {
        "source_type": "description",
        "source_id": "desc_003"
      },
      {
        "source_type": "message_section",
        "source_id": "msgsec_002"
      }
    ],
    "created_at": "2026-05-08T08:32:00+09:00",
    "updated_at": "2026-05-08T08:32:00+09:00",
    "confidence": "medium",
    "stability": "semi_stable",
    "importance": "low",
    "status": "active"
  }
]
```

### 14.6 TimeRefs 与 TimeLinks

```json
{
  "time_refs": [
    {
      "id": "time_001",
      "raw_text": "早上",
      "time_domain": "real_world",
      "time_kind": "vague",
      "certainty": "vague",
      "anchor_at": "2026-05-08T08:30:00+09:00",
      "anchor_timezone": "Asia/Tokyo",
      "anchor_utc_offset": "+09:00",
      "normalized_start": "2026-05-08T06:00:00+09:00",
      "normalized_end": "2026-05-08T10:00:00+09:00",
      "normalized_timezone": "Asia/Tokyo",
      "normalized_utc_offset": "+09:00"
    },
    {
      "id": "time_002",
      "raw_text": "经常",
      "time_domain": "real_world",
      "time_kind": "recurrence",
      "certainty": "vague",
      "recurrence_rule": null
    }
  ],
  "time_links": [
    {
      "memory_type": "event",
      "memory_id": "event_001",
      "time_ref_id": "time_001",
      "time_role": "occurred_at",
      "confidence": "medium"
    },
    {
      "memory_type": "description",
      "memory_id": "desc_003",
      "time_ref_id": "time_002",
      "time_role": "recurrence",
      "confidence": "medium"
    }
  ]
}
```

## 15. 提取与更新流程

建议系统每次收到新消息后按以下顺序处理：

1. 保存当前会话系统的 `messages`
2. 将 `messages` 切分为 `message_sections`
3. 判断是否包含 `Event`
4. 为 `Event` 生成 `title` 和 `summary`
5. 从 `Event` 中抽取多个 `Description`
6. 抽取 `Entity`
7. 从 `Description`、`Event` 和 `message_sections` 中抽取 `Property`
8. 抽取语义时间表达，写入或复用 `memory_time_refs`
9. 用 `memory_time_links` 把时间挂到对应 `Event`、`Description`、`Property`、`Entity` 或 `message_section`
10. 由 LLM 结合候选记忆、实体描述和来源片段判断是否已有相似 `Event` 或 `Property`
11. 判断是补充、矛盾、修正还是过期
12. 建立 `Link`
13. 写入 `memory_sources`，保证所有记忆能追溯到 `message_sections`
14. 按需写入或刷新 `memory_embeddings`

## 16. 语义合并规则

### 16.1 Event 合并

判断两个 `Event` 是否可能是同一事件，可以看：

- 标题语义是否相似
- `occurred_at` 角色对应的 `memory_time_refs` 是否接近
- 涉及实体是否相同
- 地点是否相同或相近
- 事件类型是否相同

如果是同一事件，建议：

- 不新建 `Event`
- 更新原 `Event`
- 追加 `Description`
- 添加新的 `message_section` 来源
- 提高 `confidence`
- 更新 `updated_at`

### 16.2 Property 合并

例如已经有：

- 用户喜欢苹果。

后来又说：

- 我挺爱吃苹果的。

不要新建完全重复的 `Property`，可以：

- 提高 `confidence`
- 追加 `source_refs`
- 更新 `updated_at`

如果后来用户说：

- 我现在不喜欢苹果了。

不要直接覆盖，应该：

- 旧 `Property` 标记 `invalidated`
- 新建新的 `Property`
- 用 `Link` 连接它们，关系类型设为 `corrects` 或 `contradicts`

## 17. 最终推荐核心模型

最精简但够用的版本是：

- `MessageSection`
- `Event`
- `Description`
- `Entity`
- `Property`
- `Link`
- `MemorySource`
- `MemoryTimeRef`
- `MemoryTimeLink`
- `MemoryEmbedding`

其中：

- `Event` = 大事件
- `Description` = 事件细节
- `Entity` = 实体
- `Property` = 实体属性
- `Link` = 任意对象之间的关系
- `MemorySource` = 所有记忆的证据和推导来源
- `MemoryTimeRef` = 语义时间表达及解析结果
- `MemoryTimeLink` = 时间表达与记忆对象之间的角色关系
- `MemoryEmbedding` = 后续检索和上下文构建的向量入口

## 18. 与当前项目的关系

当前项目已经有一套现成的对话存储结构，主要是：

- `users`
- `sessions`
- `messages`

对应的 PostgreSQL schema 目前位于 [database/postgres/schema.sql](../database/postgres/schema.sql)。本设计文档描述的是未来可以在此基础上扩展的“记忆层”模型，而不是立刻替换现有会话存储。

如果后续要落地，建议：

- 保留现有对话表作为会话基础层
- 另外增加本文中的记忆表
- 通过 `session_id`、`message_id`、`message_section_id` 把两套系统串起来

这样可以保持现有会话能力不变，同时逐步接入更强的长期记忆与知识抽取能力。
