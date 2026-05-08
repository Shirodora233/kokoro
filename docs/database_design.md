# 数据库设计文档：记忆模型

本文档描述一套面向记忆系统的数据库设计。目标是把「发生过的事」「事件中的细节」「长期稳定事实」「实体之间的关系」分层存储，并且让每一条记忆都能追溯到原始消息片段 `section_raw_msg`。

## 1. 设计目标

这套模型的核心原则是：

- `Event` 负责记录发生过的事。
- `Description` 负责记录事件中的可拆分信息点。
- `Entity` 负责记录被描述的对象。
- `Property` 负责记录实体的长期或半长期事实。
- `Link` 负责连接任意对象，并解释它们为什么有关。
- 所有可入库的记忆都必须能追溯到至少一个 `section_raw_msg`。

这样可以同时支持：

- 一个 `Event` 拥有多个 `Description`。
- 不同 `Description` 之间跨事件连接。
- `Property` 来源于 `Event`、`Description` 和原始消息。
- 一个 `Entity` 被多个 `Property` 描述。
- 记忆的来源、推导过程和失效过程都可审计。

## 2. 总体分层

建议把数据分成 5 层：

1. `RawMessage / SectionRawMsg`：原始来源层。
2. `Event`：大事件层。
3. `Description`：事件细节层。
4. `Entity`：实体层。
5. `Property`：知识层。

另外增加一层统一关系表：

- `Link`：用于连接任意对象。

可以把它理解为：

- `Event` 是故事层。
- `Description` 是细节层。
- `Entity / Property` 是知识层。
- `Link` 是关联层。
- `SectionRawMsg` 是证据层。

## 3. 原始来源层

msg_id

### 3.2 强制约束

建议约束：

- `Event` 必须至少关联一个 `section_raw_msg_id`。
- `Description` 必须至少关联一个 `section_raw_msg_id`。
- `Property` 必须至少关联一个来源引用，来源可以是 `section_raw_msg`、`event` 或 `description`，但最终仍要能追溯到 `section_raw_msg`。
- `Link` 也应保留来源引用，便于解释为什么建立该连接。

## 4. Event 设计

`Event` 表示一个可被标题概括的“大事件”。它不应塞入太多细节，细节由 `Description` 承担。

示例：

```json
{
  "id": "event_001",
  "title": "早上电车撞鹿导致列车延误",
  "summary": "早上乘坐的电车因为撞到鹿而发生延误。",
  "event_type": "incident(*字段功能待验证)", 
  "status": "active",
  "source_section_raw_msg_ids": ["section_rawmsg_001"],
  "created_at": "2026-05-08T08:31:00+09:00",
  "updated_at": "2026-05-08T08:31:00+09:00",
  "occurred_at": "2026-05-08T07:50:00+09:00",
  "valid_from": "2026-05-08T07:50:00+09:00",
  "valid_to": null,
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
| `occurred_at` | 事件实际发生时间 |
| `created_at` | 记忆进入系统的时间 |
| `updated_at` | 最近更新时间 |
| `valid_from` | 事实开始生效时间 |
| `valid_to` | 事实失效时间 |
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
  "content": "撞到的是鹿。",
  "description_type": "detail",
  "source_section_raw_msg_ids": ["section_rawmsg_001"],
  "created_at": "2026-05-08T08:31:10+09:00",
  "updated_at": "2026-05-08T08:31:10+09:00",
  "valid_from": "2026-05-08T07:50:00+09:00",
  "valid_to": null,
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
  "content": "这次电车延误发生在早上。",
  "description_type": "time_detail",
  "source_section_raw_msg_ids": ["section_rawmsg_001"],
  "created_at": "2026-05-08T08:31:12+09:00",
  "updated_at": "2026-05-08T08:31:12+09:00",
  "valid_from": "2026-05-08T07:00:00+09:00",
  "valid_to": null,
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
  "valid_from": "2026-05-08T08:40:00+09:00",
  "valid_to": null,
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
  "name": "鹿",
  "entity_type": "animal",
  "aliases": ["deer"],
  "created_at": "2026-05-08T08:31:30+09:00",
  "updated_at": "2026-05-08T08:31:30+09:00",
  "metadata": {
    "canonical_name": "鹿"
  }
}
```

用户实体示例：

```json
{
  "id": "entity_user",
  "name": "用户",
  "entity_type": "person",
  "aliases": ["我", "user"],
  "created_at": "2026-05-08T08:31:30+09:00",
  "updated_at": "2026-05-08T08:31:30+09:00"
}
```

### 6.1 Entity 建议字段

- `name`
- `entity_type`
- `aliases`
- `metadata`

`Entity` 本身尽量保持稳定，不要塞太多会频繁变化的事实。

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
  "entity_id": "entity_user",
  "property_name": "likes",
  "property_value": "苹果",
  "property_text": "用户喜欢苹果。",
  "property_type": "preference",
  "source_refs": [
    {
      "source_type": "section_raw_msg",
      "source_id": "section_rawmsg_010"
    }
  ],
  "created_at": "2026-05-08T09:00:00+09:00",
  "updated_at": "2026-05-08T09:00:00+09:00",
  "valid_from": "2026-05-08T09:00:00+09:00",
  "valid_to": null,
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
  "property_name": "may_enter",
  "property_value": "电车轨道",
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
      "source_type": "section_raw_msg",
      "source_id": "section_rawmsg_001"
    }
  ],
  "created_at": "2026-05-08T08:35:00+09:00",
  "updated_at": "2026-05-08T08:35:00+09:00",
  "valid_from": "2026-05-08T08:35:00+09:00",
  "valid_to": null,
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
- 设置 `valid_to` 和 `invalidated_at`
- 新建新的 `Property`
- 用 `Link` 把两者连接起来，说明是 `corrects` 或 `contradicts`

示例：

```json
{
  "id": "prop_001",
  "property_text": "用户喜欢苹果。",
  "status": "invalidated",
  "valid_to": "2026-05-08T10:00:00+09:00",
  "invalidated_at": "2026-05-08T10:00:00+09:00",
  "invalidated_by": "prop_003"
}
```

## 8. 时间字段设计

建议所有主要对象都统一支持以下时间字段：

- `created_at`
- `updated_at`
- `observed_at`
- `occurred_at`
- `valid_from`
- `valid_to`
- `invalidated_at`
- `expired_at`

### 8.1 区别

| 字段 | 含义 |
| --- | --- |
| `created_at` | 系统什么时候记录这条记忆 |
| `observed_at` | 什么时候从用户那里观察到这条信息 |
| `occurred_at` | 事件实际发生时间，仅 `Event` 常用 |
| `valid_from` | 事实从什么时候开始有效 |
| `valid_to` | 事实到什么时候不再有效 |
| `invalidated_at` | 被新信息推翻的时间 |
| `expired_at` | 因为太久没有使用而自然过期 |

### 8.2 示例

“我以前喜欢苹果，但现在不喜欢了。”

可以把旧 `Property` 失效掉，再写入新 `Property`。

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

## 11. 关系型数据库表设计

如果使用关系型数据库，建议采用以下表结构。

### 11.1 `section_raw_msg`

```sql
CREATE TABLE section_raw_msg (
    id TEXT PRIMARY KEY,
    raw_msg_id TEXT NOT NULL,
    conversation_id TEXT,
    role TEXT,
    section_text TEXT NOT NULL,
    start_char INTEGER,
    end_char INTEGER,
    created_at DATETIME NOT NULL,
    metadata JSON
);
```

### 11.2 `event`

```sql
CREATE TABLE event (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    event_type TEXT,
    status TEXT DEFAULT 'active',
    occurred_at DATETIME,
    observed_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    valid_from DATETIME,
    valid_to DATETIME,
    invalidated_at DATETIME,
    expired_at DATETIME,
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    importance TEXT CHECK (importance IN ('high', 'medium', 'low')),
    metadata JSON
);
```

### 11.3 `event_source`

```sql
CREATE TABLE event_source (
    event_id TEXT NOT NULL,
    section_raw_msg_id TEXT NOT NULL,
    PRIMARY KEY (event_id, section_raw_msg_id)
);
```

### 11.4 `description`

```sql
CREATE TABLE description (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    content TEXT NOT NULL,
    description_type TEXT,
    status TEXT DEFAULT 'active',
    observed_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    valid_from DATETIME,
    valid_to DATETIME,
    invalidated_at DATETIME,
    expired_at DATETIME,
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    importance TEXT CHECK (importance IN ('high', 'medium', 'low')),
    metadata JSON
);
```

### 11.5 `description_source`

```sql
CREATE TABLE description_source (
    description_id TEXT NOT NULL,
    section_raw_msg_id TEXT NOT NULL,
    PRIMARY KEY (description_id, section_raw_msg_id)
);
```

### 11.6 `entity`

```sql
CREATE TABLE entity (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT,
    aliases JSON,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    metadata JSON
);
```

### 11.7 `property`

```sql
CREATE TABLE property (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    property_name TEXT NOT NULL,
    property_value TEXT,
    property_text TEXT NOT NULL,
    property_type TEXT,
    status TEXT DEFAULT 'active',
    stability TEXT CHECK (stability IN ('stable', 'semi_stable', 'temporary')),
    observed_at DATETIME,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    valid_from DATETIME,
    valid_to DATETIME,
    invalidated_at DATETIME,
    expired_at DATETIME,
    invalidated_by TEXT,
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    importance TEXT CHECK (importance IN ('high', 'medium', 'low')),
    metadata JSON
);
```

### 11.8 `property_source`

```sql
CREATE TABLE property_source (
    property_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    PRIMARY KEY (property_id, source_type, source_id)
);
```

### 11.9 `link`

```sql
CREATE TABLE link (
    id TEXT PRIMARY KEY,
    from_type TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_type TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    reason TEXT,
    status TEXT DEFAULT 'active',
    confidence TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    valid_from DATETIME,
    valid_to DATETIME,
    invalidated_at DATETIME,
    expired_at DATETIME,
    metadata JSON
);
```

### 11.10 `link_source`

```sql
CREATE TABLE link_source (
    link_id TEXT NOT NULL,
    section_raw_msg_id TEXT NOT NULL,
    PRIMARY KEY (link_id, section_raw_msg_id)
);
```

## 12. 推荐约束

建议补充以下约束或索引：

- `event_source.event_id`、`description.event_id`、`property.entity_id`、`link.from_id`、`link.to_id` 建索引。
- `section_raw_msg.raw_msg_id` 建索引。
- `property` 对 `(entity_id, property_name, status)` 建复合索引。
- `event` 对 `(event_type, occurred_at)` 建索引。
- `link` 对 `(from_type, from_id)` 和 `(to_type, to_id)` 建索引。
- 对高频去重字段设置唯一性或近似唯一性约束，例如 `dedup_key`。

## 13. 图数据库映射

如果使用 Neo4j，可以映射为：

- `(:RawMessage)`
- `(:SectionRawMsg)`
- `(:Event)`
- `(:Description)`
- `(:Entity)`
- `(:Property)`

关系可以映射为：

- `(:RawMessage)-[:HAS_SECTION]->(:SectionRawMsg)`
- `(:Event)-[:HAS_DESCRIPTION]->(:Description)`
- `(:Event)-[:SUPPORTED_BY]->(:SectionRawMsg)`
- `(:Description)-[:SUPPORTED_BY]->(:SectionRawMsg)`
- `(:Property)-[:SUPPORTED_BY]->(:SectionRawMsg)`
- `(:Property)-[:DESCRIBES]->(:Entity)`
- `(:Description)-[:MENTIONS]->(:Entity)`
- `(:Event)-[:MENTIONS]->(:Entity)`
- `(:Description)-[:RELATED_TO {relation_type, reason, confidence, created_at, valid_from, valid_to}]->(:Description)`
- `(:Property)-[:DERIVED_FROM]->(:Event)`
- `(:Property)-[:DERIVED_FROM]->(:Description)`

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
- 去重和审计

## 14. 一条完整示例

用户原话：

> 早上电车撞鹿导致列车延误。听说这种事在那边经常发生，鹿会闯进轨道。

### 14.1 SectionRawMsg

```json
[
  {
    "id": "section_rawmsg_001",
    "raw_msg_id": "rawmsg_001",
    "section_text": "早上电车撞鹿导致列车延误。",
    "created_at": "2026-05-08T08:30:00+09:00"
  },
  {
    "id": "section_rawmsg_002",
    "raw_msg_id": "rawmsg_001",
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
  "status": "active",
  "occurred_at": "2026-05-08T07:30:00+09:00",
  "created_at": "2026-05-08T08:31:00+09:00",
  "updated_at": "2026-05-08T08:31:00+09:00",
  "valid_from": "2026-05-08T07:30:00+09:00",
  "valid_to": null,
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
    "content": "电车撞到的是鹿。",
    "description_type": "detail",
    "source_section_raw_msg_ids": ["section_rawmsg_001"],
    "confidence": "high"
  },
  {
    "id": "desc_002",
    "event_id": "event_001",
    "content": "这件事导致列车延误。",
    "description_type": "result",
    "source_section_raw_msg_ids": ["section_rawmsg_001"],
    "confidence": "high"
  },
  {
    "id": "desc_003",
    "event_id": "event_001",
    "content": "这种鹿闯入轨道导致交通异常的事情在当地可能经常发生。",
    "description_type": "frequency",
    "source_section_raw_msg_ids": ["section_rawmsg_002"],
    "confidence": "medium"
  }
]
```

### 14.4 Entities

```json
[
  {
    "id": "entity_deer",
    "name": "鹿",
    "entity_type": "animal"
  },
  {
    "id": "entity_train",
    "name": "电车",
    "entity_type": "transport"
  },
  {
    "id": "entity_track",
    "name": "轨道",
    "entity_type": "place"
  }
]
```

### 14.5 Property

```json
[
  {
    "id": "prop_001",
    "entity_id": "entity_deer",
    "property_name": "may_enter",
    "property_value": "轨道",
    "property_text": "鹿可能会闯入电车轨道。",
    "property_type": "general_fact",
    "source_refs": [
      {
        "source_type": "description",
        "source_id": "desc_003"
      },
      {
        "source_type": "section_raw_msg",
        "source_id": "section_rawmsg_002"
      }
    ],
    "created_at": "2026-05-08T08:32:00+09:00",
    "updated_at": "2026-05-08T08:32:00+09:00",
    "valid_from": "2026-05-08T08:32:00+09:00",
    "valid_to": null,
    "confidence": "medium",
    "stability": "semi_stable",
    "importance": "low",
    "status": "active"
  }
]
```

## 15. 提取与更新流程

建议系统每次收到新消息后按以下顺序处理：

1. 保存 `RawMessage`
2. 切分 `SectionRawMsg`
3. 判断是否包含 `Event`
4. 为 `Event` 生成 `title` 和 `summary`
5. 从 `Event` 中抽取多个 `Description`
6. 抽取 `Entity`
7. 从 `Description`、`Event` 和 `RawMessage` 中抽取 `Property`
8. 查重：是否已有相似 `Event` 或 `Property`
9. 判断是补充、矛盾、修正还是过期
10. 建立 `Link`
11. 写入数据库

## 16. 去重与合并规则

### 16.1 Event 去重

判断两个 `Event` 是否可能是同一事件，可以看：

- 标题语义是否相似
- `occurred_at` 是否接近
- 涉及实体是否相同
- 地点是否相同或相近
- 事件类型是否相同

如果是同一事件，建议：

- 不新建 `Event`
- 更新原 `Event`
- 追加 `Description`
- 添加新的 `source_section_raw_msg`
- 提高 `confidence`
- 更新 `updated_at`

### 16.2 Property 去重

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

- `SectionRawMsg`
- `Event`
- `Description`
- `Entity`
- `Property`
- `Link`

其中：

- `Event` = 大事件
- `Description` = 事件细节
- `Entity` = 实体
- `Property` = 实体属性
- `Link` = 任意对象之间的关系
- `Source` = 所有记忆的证据

## 18. 与当前项目的关系

当前项目已经有一套现成的对话存储结构，主要是：

- `users`
- `sessions`
- `messages`

对应的 PostgreSQL schema 目前位于 [database/postgres/schema.sql](../database/postgres/schema.sql)。本设计文档描述的是未来可以在此基础上扩展的“记忆层”模型，而不是立刻替换现有会话存储。

如果后续要落地，建议：

- 保留现有对话表作为会话基础层
- 另外增加本文中的记忆表
- 通过 `conversation_id`、`raw_msg_id`、`section_raw_msg_id` 把两套系统串起来

这样可以保持现有会话能力不变，同时逐步接入更强的长期记忆与知识抽取能力。
