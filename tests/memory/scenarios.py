"""Shared memory test scenarios and fixtures."""

from __future__ import annotations

from memory.models import MemoryInputMessage, MemoryTurnInput

USER_ID = "usr_memory_scenario"
SESSION_ID = "ses_memory_scenario"


def turn(
    *,
    message_id: str = "msg_memory_scenario",
    content: str = "想起来前几天去吃打抛饭，但是那个吃起来很辣。",
    created_at: str = "2026-06-02T10:00:00+08:00",
    timezone: str = "Asia/Shanghai",
) -> MemoryTurnInput:
    message = MemoryInputMessage(
        id=message_id,
        role="user",
        content=content,
        user_id=USER_ID,
        session_id=SESSION_ID,
        created_at=created_at,
    )
    return MemoryTurnInput(
        user_id=USER_ID,
        session_id=SESSION_ID,
        timezone=timezone,
        new_message=message,
        conversation_context=[message],
    )


def duplicate_entity_property_json(
    *,
    event_entity_client_id: str = "entity_food",
    top_entity_client_id: str = "entity_food",
) -> str:
    return """
{
  "event_candidates": [
    {
      "client_id": "event_pad_krapow",
      "title": "吃打抛饭体验",
      "event_type": "story_beat",
      "descriptions": [
        {
          "client_id": "desc_pad_krapow",
          "text": "用户前几天去吃了打抛饭，感觉很辣。",
          "description_type": "detail",
          "source_message_ids": ["msg_memory_scenario"],
          "source_quote": "前几天去吃打抛饭"
        }
      ],
      "entities": [
        {
          "client_id": "__EVENT_ENTITY_CLIENT_ID__",
          "name": "打抛饭",
          "entity_type": "object",
          "identity_summary": "一种食物",
          "properties": [
            {
              "client_id": "prop_spicy",
              "text": "打抛饭吃起来很辣",
              "property_type": "attribute",
              "source_message_ids": ["msg_memory_scenario"],
              "source_quote": "那个吃起来很辣"
            }
          ],
          "source_message_ids": ["msg_memory_scenario"],
          "source_quote": "打抛饭"
        }
      ],
      "source_message_ids": ["msg_memory_scenario"],
      "source_quote": "想起来前几天去吃打抛饭，但是那个吃起来很辣。"
    }
  ],
  "entity_candidates": [
    {
      "client_id": "__TOP_ENTITY_CLIENT_ID__",
      "name": "打抛饭",
      "entity_type": "object",
      "identity_summary": "一种食物",
      "properties": [
        {
          "client_id": "prop_spicy",
          "text": "打抛饭吃起来很辣",
          "property_type": "attribute",
          "source_message_ids": ["msg_memory_scenario"],
          "source_quote": "那个吃起来很辣"
        }
      ],
      "source_message_ids": ["msg_memory_scenario"],
      "source_quote": "打抛饭"
    }
  ]
}
""".replace(
        "__EVENT_ENTITY_CLIENT_ID__",
        event_entity_client_id,
    ).replace(
        "__TOP_ENTITY_CLIENT_ID__",
        top_entity_client_id,
    )


def relative_plan_json() -> str:
    return """
{
  "event_candidates": [
    {
      "client_id": "event_follow_up",
      "title": "会诊安排",
      "event_type": "appointment",
      "time": {
        "client_id": "time_follow_up",
        "role": "scheduled_at",
        "raw_text": "明天上午十点",
        "time_kind": "relative",
        "timeline_kind": "real_world",
        "certainty": "resolved",
        "anchor_timezone": "Asia/Shanghai",
        "anchor_utc_offset": "+08:00",
        "anchor_message_id": "msg_memory_scenario",
        "resolved_start": "2026-06-03T10:00:00+08:00",
        "granularity": "minute",
        "source_message_ids": ["msg_memory_scenario"],
        "source_quote": "明天上午十点"
      },
      "descriptions": [
        {
          "client_id": "desc_follow_up",
          "text": "用户计划和林医生复诊，地点在静安门诊。",
          "description_type": "detail",
          "time": {"role": "same_as_parent"},
          "source_message_ids": ["msg_memory_scenario"],
          "source_quote": "我要和林医生复诊，地点在静安的门诊"
        }
      ],
      "entities": [
        {
          "client_id": "entity_doctor",
          "name": "林医生",
          "entity_type": "person",
          "identity_summary": "医生",
          "source_message_ids": ["msg_memory_scenario"],
          "source_quote": "林医生"
        },
        {
          "client_id": "entity_clinic",
          "name": "静安门诊",
          "entity_type": "place",
          "identity_summary": "复诊地点",
          "source_message_ids": ["msg_memory_scenario"],
          "source_quote": "静安的门诊"
        }
      ],
      "source_message_ids": ["msg_memory_scenario"],
      "source_quote": "明天上午十点我要和林医生复诊，地点在静安的门诊"
    }
  ],
  "entity_candidates": []
}
"""
