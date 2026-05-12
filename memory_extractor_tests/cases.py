"""Extractor integration test cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memory.models import (
    ActiveMemoryContext,
    ConversationContextState,
    MemoryInputMessage,
    MemoryRecord,
    MemoryTurnInput,
)


@dataclass(frozen=True)
class ExpectedSignal:
    label: str
    required_types: tuple[str, ...] = ()
    any_text_contains: tuple[str, ...] = ()
    min_records: int | None = None
    max_records: int | None = None


@dataclass(frozen=True)
class ExtractorTestCase:
    case_id: str
    title: str
    description: str
    turn: MemoryTurnInput
    expected_signals: tuple[ExpectedSignal, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def build_cases() -> list[ExtractorTestCase]:
    return [
        _tea_preference_case(),
        _fictional_deer_case(),
        _relative_time_case(),
        _active_context_update_case(),
        _do_not_remember_case(),
    ]


def _message(
    message_id: str,
    role: str,
    content: str,
    session_id: str,
    user_id: str | None = "usr_extractor_test",
    created_at: str = "2026-05-12T09:00:00+08:00",
) -> MemoryInputMessage:
    return MemoryInputMessage(
        id=message_id,
        role=role,
        content=content,
        session_id=session_id,
        user_id=user_id,
        created_at=created_at,
    )


def _turn(
    session_id: str,
    messages: list[MemoryInputMessage],
    active_memory_context: ActiveMemoryContext | None = None,
    timezone: str = "Asia/Shanghai",
) -> MemoryTurnInput:
    return MemoryTurnInput(
        user_id="usr_extractor_test",
        session_id=session_id,
        new_message=messages[-1],
        timezone=timezone,
        conversation_context=messages,
        context_state=ConversationContextState(
            context_start_index=0,
            total_messages=len(messages),
            max_context_messages=20,
            active_message_ids=[message.id for message in messages],
        ),
        active_memory_context=active_memory_context,
    )


def _tea_preference_case() -> ExtractorTestCase:
    session_id = "ses_extractor_tea"
    messages = [
        _message(
            "msg_tea_1",
            "user",
            "我叫 Alice，平时喜欢安静一点的对话。",
            session_id,
            created_at="2026-05-12T09:00:00+08:00",
        ),
        _message(
            "msg_tea_2",
            "assistant",
            "好的，我会尽量保持简洁温和。",
            session_id,
            user_id=None,
            created_at="2026-05-12T09:00:05+08:00",
        ),
        _message(
            "msg_tea_3",
            "user",
            "我每天早上都喝茉莉花茶，基本不喝咖啡。",
            session_id,
            created_at="2026-05-12T09:01:00+08:00",
        ),
    ]
    return ExtractorTestCase(
        case_id="tea_preference",
        title="用户偏好和身份信息",
        description="最新消息包含稳定饮品偏好，应该抽取偏好或属性类记忆。",
        turn=_turn(session_id, messages),
        expected_signals=(
            ExpectedSignal(
                label="至少抽取一条候选记忆",
                min_records=1,
            ),
            ExpectedSignal(
                label="包含 property 或 description",
                required_types=("property", "description"),
            ),
            ExpectedSignal(
                label="文本提到茉莉花茶或咖啡偏好",
                any_text_contains=("茉莉", "jasmine", "咖啡", "coffee"),
            ),
        ),
    )


def _fictional_deer_case() -> ExtractorTestCase:
    session_id = "ses_extractor_deer"
    messages = [
        _message(
            "msg_deer_1",
            "user",
            "我在写一个故事，主角不是人，是一只鹿。",
            session_id,
            created_at="2026-05-12T10:00:00+08:00",
        ),
        _message(
            "msg_deer_2",
            "assistant",
            "这只鹿可以作为故事的核心意象。",
            session_id,
            user_id=None,
            created_at="2026-05-12T10:00:05+08:00",
        ),
        _message(
            "msg_deer_3",
            "user",
            "那只闯入铁路的鹿是在很久很久以前出现的，"
            "故事里它守着废弃车站一两年。",
            session_id,
            created_at="2026-05-12T10:01:00+08:00",
        ),
    ]
    return ExtractorTestCase(
        case_id="fictional_deer",
        title="故事实体、事件和虚构时间",
        description="上下文包含虚构故事，应识别鹿、铁路/车站和模糊时间。",
        turn=_turn(session_id, messages),
        expected_signals=(
            ExpectedSignal(label="至少抽取两条候选记忆", min_records=2),
            ExpectedSignal(
                label="包含 entity 或 event",
                required_types=("entity", "event"),
            ),
            ExpectedSignal(
                label="文本提到鹿或铁路车站",
                any_text_contains=("鹿", "deer", "铁路", "rail", "车站", "station"),
            ),
            ExpectedSignal(
                label="包含 time_ref 或文本提到模糊时间",
                required_types=("time_ref", "description", "event"),
                any_text_contains=("很久", "一两年", "long ago", "year"),
            ),
        ),
    )


def _relative_time_case() -> ExtractorTestCase:
    session_id = "ses_extractor_time"
    messages = [
        _message(
            "msg_time_1",
            "user",
            "我最近身体恢复得还不错。",
            session_id,
            created_at="2026-05-12T11:00:00+08:00",
        ),
        _message(
            "msg_time_2",
            "user",
            "明天上午十点我要和林医生复诊，地点在静安的门诊。",
            session_id,
            created_at="2026-05-12T11:02:00+08:00",
        ),
    ]
    return ExtractorTestCase(
        case_id="relative_time",
        title="相对时间和日程事件",
        description="最新消息包含相对时间、人物和地点，时区为 Asia/Shanghai。",
        turn=_turn(session_id, messages),
        expected_signals=(
            ExpectedSignal(label="至少抽取一条候选记忆", min_records=1),
            ExpectedSignal(
                label="包含 event 或 time_ref",
                required_types=("event", "time_ref"),
            ),
            ExpectedSignal(
                label="文本提到复诊、林医生或明天上午十点",
                any_text_contains=("复诊", "林医生", "明天", "十点", "10", "doctor"),
            ),
        ),
    )


def _active_context_update_case() -> ExtractorTestCase:
    session_id = "ses_extractor_active_context"
    active_context = ActiveMemoryContext(
        event_memories=[
            MemoryRecord(
                id="evt_tea_topic",
                memory_type="event",
                text="用户正在讨论自己的茶饮偏好。",
                metadata={"identity_summary": "当前用户的饮品偏好话题。"},
            )
        ],
        entity_memories=[
            MemoryRecord(
                id="ent_jasmine_tea",
                memory_type="entity",
                text="茉莉花茶是用户喜欢的饮品。",
                metadata={"identity_summary": "用户常喝的茶饮。"},
            )
        ],
    )
    messages = [
        _message(
            "msg_active_1",
            "user",
            "我们继续说我的饮品偏好。",
            session_id,
            created_at="2026-05-12T12:00:00+08:00",
        ),
        _message(
            "msg_active_2",
            "user",
            "还是那个茉莉花茶，我补充一下，最好少糖，不要加奶。",
            session_id,
            created_at="2026-05-12T12:01:00+08:00",
        ),
    ]
    return ExtractorTestCase(
        case_id="active_context_update",
        title="已有活跃记忆下的补充信息",
        description="active context 已有茶饮偏好，应抽取新的补充属性。",
        turn=_turn(session_id, messages, active_memory_context=active_context),
        expected_signals=(
            ExpectedSignal(label="至少抽取一条候选记忆", min_records=1),
            ExpectedSignal(
                label="包含 property 或 description",
                required_types=("property", "description"),
            ),
            ExpectedSignal(
                label="文本提到少糖或不加奶",
                any_text_contains=("少糖", "不加奶", "milk", "sugar"),
            ),
        ),
    )


def _do_not_remember_case() -> ExtractorTestCase:
    session_id = "ses_extractor_ignore"
    messages = [
        _message(
            "msg_ignore_1",
            "user",
            "刚才我打错字了，上一句不用记。",
            session_id,
            created_at="2026-05-12T13:00:00+08:00",
        ),
        _message(
            "msg_ignore_2",
            "user",
            "这条也是临时测试消息，没有任何长期价值。",
            session_id,
            created_at="2026-05-12T13:00:20+08:00",
        ),
    ]
    return ExtractorTestCase(
        case_id="do_not_remember",
        title="明确不需要记忆的临时消息",
        description="用户明确表示不用记，理想结果是返回空候选。",
        turn=_turn(session_id, messages),
        expected_signals=(
            ExpectedSignal(label="不应抽取候选记忆", max_records=0),
        ),
    )
