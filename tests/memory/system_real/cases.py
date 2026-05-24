"""Scenario definitions for real memory-system integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from memory.models import (
    ActiveMemoryContext,
    ConversationContextState,
    MemoryInputMessage,
    MemoryRecord,
    MemorySourceRef,
    MemoryTurnInput,
)


@dataclass(frozen=True)
class StoreSignal:
    label: str
    required_all_types: tuple[str, ...] = ()
    any_text_contains: tuple[str, ...] = ()
    all_text_contains: tuple[str, ...] = ()
    min_records: int | None = None
    max_exact_duplicates: int | None = None


@dataclass(frozen=True)
class WriteSignal:
    label: str
    required_actions: tuple[str, ...] = ()
    min_created_records: int | None = None
    min_attached_records: int | None = None
    expect_no_failures: bool = True


@dataclass(frozen=True)
class MemorySystemTestScenario:
    scenario_id: str
    title: str
    description: str
    turns: list[MemoryTurnInput]
    expected_store_signals: tuple[StoreSignal, ...]
    expected_write_signals: tuple[WriteSignal, ...] = ()
    seed_records: tuple[MemoryRecord, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


def build_scenarios() -> list[MemorySystemTestScenario]:
    return [
        _active_tea_reuse_scenario(),
        _appointment_scenario(),
        _fictional_radio_followup_scenario(),
    ]


def _active_tea_reuse_scenario() -> MemorySystemTestScenario:
    session_id = "ses_real_system_tea"
    seed = MemoryRecord(
        id="ent_seed_jasmine_tea",
        memory_type="entity",
        text="茉莉花茶",
        source_refs=[MemorySourceRef(source_type="manual_seed", source_id="seed")],
        metadata={
            "candidate_client_id": "ent_seed_jasmine_tea",
            "entity_type": "concept",
            "identity_summary": "用户正在讨论的茶饮。",
            "user_id": "usr_real_system_test",
            "session_id": session_id,
        },
    )
    active_context = ActiveMemoryContext(
        entity_memories=[seed],
        last_refreshed_at_message_id="msg_tea_seed",
    )
    turn = _turn(
        session_id=session_id,
        messages=[
            _message(
                "msg_tea_1",
                "user",
                "还是那个茉莉花茶，我补充一下，最好少糖，不要加奶。",
                session_id,
                created_at="2026-05-13T10:00:00+08:00",
            )
        ],
        active_memory_context=active_context,
    )
    return MemorySystemTestScenario(
        scenario_id="active_tea_reuse",
        title="活跃上下文里的茶饮偏好补充",
        description=(
            "预置已有实体“茉莉花茶”，真实 LLM 应把少糖、不加奶抽为候选属性；"
            "系统应尽量复用已有实体并挂载新属性。"
        ),
        seed_records=(seed,),
        turns=[turn],
        expected_store_signals=(
            StoreSignal(label="最终 store 至少包含预置实体和新属性", min_records=3),
            StoreSignal(label="包含 property", required_all_types=("property",)),
            StoreSignal(
                label="文本提到少糖和不加奶",
                all_text_contains=("少糖", "不加奶"),
            ),
            StoreSignal(
                label="同类型同文本重复不超过 1",
                max_exact_duplicates=1,
            ),
        ),
        expected_write_signals=(
            WriteSignal(
                label="write plan 应出现 reuse 和 attach",
                required_actions=("reuse", "attach"),
                min_attached_records=1,
            ),
        ),
    )


def _appointment_scenario() -> MemorySystemTestScenario:
    session_id = "ses_real_system_appointment"
    messages = [
        _message(
            "msg_appointment_1",
            "user",
            "我最近身体恢复得还不错。",
            session_id,
            created_at="2026-05-13T11:00:00+08:00",
        ),
        _message(
            "msg_appointment_2",
            "user",
            "明天上午十点我要和林医生复诊，地点在静安的门诊。",
            session_id,
            created_at="2026-05-13T11:02:00+08:00",
        ),
    ]
    return MemorySystemTestScenario(
        scenario_id="appointment_full_flow",
        title="相对时间会诊安排完整写入链路",
        description=(
            "真实 LLM 抽取相对时间、会诊安排、人物和地点，系统完成写入与"
            "active context 刷新。"
        ),
        turns=[_turn(session_id=session_id, messages=messages)],
        expected_store_signals=(
            StoreSignal(label="至少写入多条结构化记忆", min_records=6),
            StoreSignal(
                label="包含 event、description、entity、time_ref、time_link",
                required_all_types=(
                    "event",
                    "description",
                    "entity",
                    "time_ref",
                    "time_link",
                ),
            ),
            StoreSignal(
                label="文本提到复诊、林医生和静安",
                all_text_contains=("复诊", "林医生", "静安"),
            ),
        ),
        expected_write_signals=(
            WriteSignal(
                label="首次写入应包含 create 或 attach",
                required_actions=("create", "attach"),
                min_created_records=1,
                min_attached_records=1,
            ),
        ),
    )


def _fictional_radio_followup_scenario() -> MemorySystemTestScenario:
    session_id = "ses_real_system_radio"
    first = _message(
        "msg_radio_1",
        "user",
        "新故事里有一个反复出现的物件，是一台蓝色收音机。",
        session_id,
        created_at="2026-05-13T15:00:00+08:00",
    )
    second = _message(
        "msg_radio_2",
        "user",
        "那台蓝色收音机在战争结束前夜突然播报不存在的海港天气。",
        session_id,
        created_at="2026-05-13T15:02:00+08:00",
    )
    return MemorySystemTestScenario(
        scenario_id="fictional_radio_followup",
        title="多轮虚构实体和故事事件",
        description=(
            "第一轮建立故事实体，第二轮继续用指代表达同一实体并补充故事事件；"
            "系统应尽量复用实体并写入事件、描述和虚构时间。"
        ),
        turns=[
            _turn(session_id=session_id, messages=[first]),
            _turn(session_id=session_id, messages=[first, second]),
        ],
        expected_store_signals=(
            StoreSignal(label="至少写入多条故事记忆", min_records=6),
            StoreSignal(
                label="包含 event、description、entity、time_ref、time_link",
                required_all_types=(
                    "event",
                    "description",
                    "entity",
                    "time_ref",
                    "time_link",
                ),
            ),
            StoreSignal(
                label="文本提到收音机、战争和海港",
                all_text_contains=("收音机", "战争", "海港"),
            ),
            StoreSignal(
                label="同类型同文本重复不超过 1",
                max_exact_duplicates=1,
            ),
        ),
        expected_write_signals=(
            WriteSignal(
                label="后续轮次应尽量出现 reuse 或 attach",
                required_actions=("reuse", "attach"),
                min_attached_records=1,
            ),
        ),
    )


def _turn(
    session_id: str,
    messages: list[MemoryInputMessage],
    active_memory_context: ActiveMemoryContext | None = None,
) -> MemoryTurnInput:
    return MemoryTurnInput(
        user_id="usr_real_system_test",
        session_id=session_id,
        new_message=messages[-1],
        timezone="Asia/Shanghai",
        conversation_context=messages,
        context_state=ConversationContextState(
            context_start_index=0,
            total_messages=len(messages),
            max_context_messages=20,
            active_message_ids=[message.id for message in messages],
        ),
        active_memory_context=active_memory_context,
    )


def _message(
    message_id: str,
    role: str,
    content: str,
    session_id: str,
    created_at: str,
) -> MemoryInputMessage:
    return MemoryInputMessage(
        id=message_id,
        role=role,  # type: ignore[arg-type]
        content=content,
        session_id=session_id,
        user_id="usr_real_system_test" if role != "assistant" else None,
        created_at=created_at,
    )
