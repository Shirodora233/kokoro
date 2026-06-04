"""Run deterministic tests for memory extraction internals."""

from __future__ import annotations

import sys
from collections.abc import Callable

from llm.interfaces import ChatCompletionResult, ChatMessageParam
from memory.extraction import LLMMemoryExtractor, MemoryCandidateCoalescer
from memory.extraction.parser import parse_extraction_response
from memory.models import MemoryInputMessage, MemoryTurnInput

USER_ID = "usr_extraction_test"
SESSION_ID = "ses_extraction_test"


def main() -> int:
    tests: list[Callable[[], None]] = [
        test_coalescer_keeps_event_entities_as_refs_and_moves_properties_top_level,
        test_coalescer_merges_same_entity_by_name_and_type_with_different_client_ids,
        test_llm_extractor_normalizes_coalesced_records_once,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"passed={len(tests)}/{len(tests)}")
    return 0


def test_coalescer_keeps_event_entities_as_refs_and_moves_properties_top_level() -> None:
    batch = parse_extraction_response(_duplicate_entity_property_json())

    coalesced = MemoryCandidateCoalescer().coalesce(batch)

    event = coalesced.event_candidates[0]
    food_refs = [entity for entity in event.entities if entity.name == "打抛饭"]
    top_food = [
        entity for entity in coalesced.entity_candidates if entity.name == "打抛饭"
    ]

    assert len(food_refs) == 1
    assert food_refs[0].client_id == "entity_food"
    assert food_refs[0].properties == []
    assert len(top_food) == 1
    assert len(top_food[0].properties) == 1
    assert top_food[0].properties[0].text == "打抛饭吃起来很辣"


def test_coalescer_merges_same_entity_by_name_and_type_with_different_client_ids() -> None:
    batch = parse_extraction_response(
        _duplicate_entity_property_json(
            event_entity_client_id="event_food",
            top_entity_client_id="top_food",
        )
    )

    coalesced = MemoryCandidateCoalescer().coalesce(batch)

    event = coalesced.event_candidates[0]
    food_refs = [entity for entity in event.entities if entity.name == "打抛饭"]
    top_food = [
        entity for entity in coalesced.entity_candidates if entity.name == "打抛饭"
    ]

    assert len(food_refs) == 1
    assert food_refs[0].client_id == "event_food"
    assert food_refs[0].properties == []
    assert len(top_food) == 1
    assert top_food[0].client_id == "event_food"
    assert len(top_food[0].properties) == 1


def test_llm_extractor_normalizes_coalesced_records_once() -> None:
    extractor = LLMMemoryExtractor(
        chat_client=_StaticChatClient(_duplicate_entity_property_json())
    )

    records = list(extractor.extract(_turn()))

    properties = [
        record
        for record in records
        if record.memory_type == "property" and record.text == "打抛饭吃起来很辣"
    ]
    has_property_links = [
        record
        for record in records
        if record.memory_type == "link"
        and record.metadata.get("relation_type") == "has_property"
        and record.metadata.get("from_client_id") == "entity_food"
        and record.metadata.get("to_client_id") == "prop_spicy"
    ]
    involves_food_links = [
        record
        for record in records
        if record.memory_type == "link"
        and record.metadata.get("relation_type") == "involves"
        and record.metadata.get("from_client_id") == "event_pad_krapow"
        and record.metadata.get("to_client_id") == "entity_food"
    ]

    assert len(properties) == 1
    assert len(has_property_links) == 1
    assert len(involves_food_links) == 1


class _StaticChatClient:
    def __init__(self, content: str) -> None:
        self.content = content

    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        return ChatCompletionResult(
            content=self.content,
            model=model or "test-model",
            usage={"total_tokens": 1},
            provider_message_id="provider_extraction_test",
        )


def _turn() -> MemoryTurnInput:
    message = MemoryInputMessage(
        id="msg_pad_krapow",
        role="user",
        content="想起来前几天去吃打抛饭，但是那个吃起来很辣。",
        user_id=USER_ID,
        session_id=SESSION_ID,
        created_at="2026-06-02T10:00:00+08:00",
    )
    return MemoryTurnInput(
        user_id=USER_ID,
        session_id=SESSION_ID,
        timezone="Asia/Shanghai",
        new_message=message,
        conversation_context=[message],
    )


def _duplicate_entity_property_json(
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
          "source_message_ids": ["msg_pad_krapow"],
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
              "source_message_ids": ["msg_pad_krapow"],
              "source_quote": "那个吃起来很辣"
            }
          ],
          "source_message_ids": ["msg_pad_krapow"],
          "source_quote": "打抛饭"
        }
      ],
      "source_message_ids": ["msg_pad_krapow"],
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
          "source_message_ids": ["msg_pad_krapow"],
          "source_quote": "那个吃起来很辣"
        }
      ],
      "source_message_ids": ["msg_pad_krapow"],
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


if __name__ == "__main__":
    sys.exit(main())
