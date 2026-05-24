# Memory Extractor Test Report

- Generated at: 2026-05-12T06:17:32.025459+00:00
- Overall: PASS
- Passed cases: 5/5
- Chat model: `mimo-v2-omni`
- Extraction model: `mimo-v2-omni`
- Base URL configured: `True`

## Scope

This report tests only `LLMMemoryExtractor`: prompt construction, real LLM call, JSON parsing, and normalization into `MemoryRecord`. It does not test memory persistence, retrieval, merge/update, or conflict resolution.

## tea_preference: PASS

**Title:** 用户偏好和身份信息

**Description:** 最新消息包含稳定饮品偏好，应该抽取偏好或属性类记忆。

**Duration:** 35.94s

### Checks

- PASS: 至少抽取一条候选记忆 - ok
- PASS: 包含 property 或 description - ok
- PASS: 文本提到茉莉花茶或咖啡偏好 - ok
- PASS: metadata 不包含 canonical_key/dedup_key - ok
- PASS: 所有候选都有 source_refs - ok
- PASS: source_refs.quote 能在对应消息中找到 - ok
- PASS: 所有候选都有非空 text - ok

### Source Messages

#### msg_tea_1 `user`

```text
我叫 Alice，平时喜欢安静一点的对话。
```

#### msg_tea_2 `assistant`

```text
好的，我会尽量保持简洁温和。
```

#### msg_tea_3 `user`

```text
我每天早上都喝茉莉花茶，基本不喝咖啡。
```

### Extracted Records

#### Record 1

```json
{
  "id": null,
  "memory_type": "property",
  "text": "Drinks jasmine tea every morning and basically doesn't drink coffee.",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_tea_3",
      "quote": "我每天早上都喝茉莉花茶，基本不喝咖啡。",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "extracted_by": "llm"
  }
}
```

## fictional_deer: PASS

**Title:** 故事实体、事件和虚构时间

**Description:** 上下文包含虚构故事，应识别鹿、铁路/车站和模糊时间。

**Duration:** 18.72s

### Checks

- PASS: 至少抽取两条候选记忆 - ok
- PASS: 包含 entity 或 event - ok
- PASS: 文本提到鹿或铁路车站 - ok
- PASS: 包含 time_ref 或文本提到模糊时间 - ok
- PASS: metadata 不包含 canonical_key/dedup_key - ok
- PASS: 所有候选都有 source_refs - ok
- PASS: source_refs.quote 能在对应消息中找到 - ok
- PASS: 所有候选都有非空 text - ok

### Source Messages

#### msg_deer_1 `user`

```text
我在写一个故事，主角不是人，是一只鹿。
```

#### msg_deer_2 `assistant`

```text
这只鹿可以作为故事的核心意象。
```

#### msg_deer_3 `user`

```text
那只闯入铁路的鹿是在很久很久以前出现的，故事里它守着废弃车站一两年。
```

### Extracted Records

#### Record 1

```json
{
  "id": null,
  "memory_type": "entity",
  "text": "A deer that is the protagonist of a story and broke into a railway.",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_deer_3",
      "quote": "那只闯入铁路的鹿",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "identity_summary": "The main character in the user's story, a deer.",
    "extracted_by": "llm"
  }
}
```

#### Record 2

```json
{
  "id": null,
  "memory_type": "time_ref",
  "text": "The deer appeared a long, long time ago in the story.",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_deer_3",
      "quote": "是在很久很久以前出现的",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "extracted_by": "llm"
  }
}
```

#### Record 3

```json
{
  "id": null,
  "memory_type": "event",
  "text": "The deer guarded an abandoned station for one to two years in the story.",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_deer_3",
      "quote": "故事里它守着废弃车站一两年",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "extracted_by": "llm"
  }
}
```

## relative_time: PASS

**Title:** 相对时间和日程事件

**Description:** 最新消息包含相对时间、人物和地点，时区为 Asia/Shanghai。

**Duration:** 38.17s

### Checks

- PASS: 至少抽取一条候选记忆 - ok
- PASS: 包含 event 或 time_ref - ok
- PASS: 文本提到复诊、林医生或明天上午十点 - ok
- PASS: metadata 不包含 canonical_key/dedup_key - ok
- PASS: 所有候选都有 source_refs - ok
- PASS: source_refs.quote 能在对应消息中找到 - ok
- PASS: 所有候选都有非空 text - ok

### Source Messages

#### msg_time_1 `user`

```text
我最近身体恢复得还不错。
```

#### msg_time_2 `user`

```text
明天上午十点我要和林医生复诊，地点在静安的门诊。
```

### Extracted Records

#### Record 1

```json
{
  "id": null,
  "memory_type": "event",
  "text": "User has a follow-up appointment with Dr. Lin on 2026-05-13 at 10:00 AM at Jing'an clinic.",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_time_2",
      "quote": "明天上午十点我要和林医生复诊，地点在静安的门诊。",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "extracted_by": "llm"
  }
}
```

#### Record 2

```json
{
  "id": null,
  "memory_type": "entity",
  "text": "Dr. Lin",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_time_2",
      "quote": "林医生",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "identity_summary": "A doctor mentioned by the user for medical follow-up.",
    "extracted_by": "llm"
  }
}
```

#### Record 3

```json
{
  "id": null,
  "memory_type": "entity",
  "text": "Jing'an clinic",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_time_2",
      "quote": "静安的门诊",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "identity_summary": "The clinic in Jing'an district where the user has appointments.",
    "extracted_by": "llm"
  }
}
```

#### Record 4

```json
{
  "id": null,
  "memory_type": "time_ref",
  "text": "2026-05-13T10:00:00+08:00",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_time_2",
      "quote": "明天上午十点",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "relative_expression": "明天上午十点",
    "extracted_by": "llm"
  }
}
```

#### Record 5

```json
{
  "id": null,
  "memory_type": "property",
  "text": "User is recovering well recently.",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_time_1",
      "quote": "我最近身体恢复得还不错。",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "extracted_by": "llm"
  }
}
```

## active_context_update: PASS

**Title:** 已有活跃记忆下的补充信息

**Description:** active context 已有茶饮偏好，应抽取新的补充属性。

**Duration:** 14.84s

### Checks

- PASS: 至少抽取一条候选记忆 - ok
- PASS: 包含 property 或 description - ok
- PASS: 文本提到少糖或不加奶 - ok
- PASS: metadata 不包含 canonical_key/dedup_key - ok
- PASS: 所有候选都有 source_refs - ok
- PASS: source_refs.quote 能在对应消息中找到 - ok
- PASS: 所有候选都有非空 text - ok

### Source Messages

#### msg_active_1 `user`

```text
我们继续说我的饮品偏好。
```

#### msg_active_2 `user`

```text
还是那个茉莉花茶，我补充一下，最好少糖，不要加奶。
```

### Extracted Records

#### Record 1

```json
{
  "id": null,
  "memory_type": "property",
  "text": "User prefers jasmine tea with less sugar and no milk.",
  "source_refs": [
    {
      "source_type": "message",
      "source_id": "msg_active_2",
      "quote": "还是那个茉莉花茶，我补充一下，最好少糖，不要加奶。",
      "span_start": null,
      "span_end": null,
      "metadata": {}
    }
  ],
  "metadata": {
    "extracted_by": "llm"
  }
}
```

## do_not_remember: PASS

**Title:** 明确不需要记忆的临时消息

**Description:** 用户明确表示不用记，理想结果是返回空候选。

**Duration:** 8.72s

### Checks

- PASS: 不应抽取候选记忆 - ok
- PASS: metadata 不包含 canonical_key/dedup_key - ok
- PASS: 所有候选都有 source_refs - ok
- PASS: source_refs.quote 能在对应消息中找到 - ok
- PASS: 所有候选都有非空 text - ok

### Source Messages

#### msg_ignore_1 `user`

```text
刚才我打错字了，上一句不用记。
```

#### msg_ignore_2 `user`

```text
这条也是临时测试消息，没有任何长期价值。
```

### Extracted Records

No records.
