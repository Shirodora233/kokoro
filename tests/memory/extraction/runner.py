"""Run deterministic tests for memory extraction internals."""

from __future__ import annotations

import sys
from collections.abc import Callable

from llm.interfaces import ChatCompletionResult, ChatMessageParam
from memory.extraction import LLMMemoryExtractor, MemoryCandidateCoalescer
from memory.extraction.parser import parse_extraction_response
from tests.memory.scenarios import (
    duplicate_entity_property_json,
    relative_plan_json,
    turn,
)


def main() -> int:
    tests: list[Callable[[], None]] = [
        test_coalescer_keeps_event_entities_as_refs_and_moves_properties_top_level,
        test_coalescer_merges_same_entity_by_name_and_type_with_different_client_ids,
        test_llm_extractor_normalizes_coalesced_records_once,
        test_llm_extractor_normalizes_relative_event_time_and_inherited_description_time,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"passed={len(tests)}/{len(tests)}")
    return 0


def test_coalescer_keeps_event_entities_as_refs_and_moves_properties_top_level() -> None:
    batch = parse_extraction_response(duplicate_entity_property_json())

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
        duplicate_entity_property_json(
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
        chat_client=_StaticChatClient(duplicate_entity_property_json())
    )

    records = list(extractor.extract(turn()))

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


def test_llm_extractor_normalizes_relative_event_time_and_inherited_description_time() -> None:
    extractor = LLMMemoryExtractor(chat_client=_StaticChatClient(relative_plan_json()))

    records = list(
        extractor.extract(
            turn(
                content="明天上午十点我要和林医生复诊，地点在静安的门诊",
            )
        )
    )

    time_refs = [
        record
        for record in records
        if record.memory_type == "time_ref"
        and record.metadata.get("candidate_client_id") == "time_follow_up"
    ]
    scheduled_links = [
        record
        for record in records
        if record.memory_type == "time_link"
        and record.metadata.get("time_ref_client_id") == "time_follow_up"
        and record.metadata.get("time_role") == "scheduled_at"
    ]
    event_links = [
        record
        for record in scheduled_links
        if record.metadata.get("target_client_id") == "event_follow_up"
    ]
    description_links = [
        record
        for record in scheduled_links
        if record.metadata.get("target_client_id") == "desc_follow_up"
    ]

    assert len(time_refs) == 1
    time_metadata = time_refs[0].metadata
    assert time_metadata["time_kind"] == "relative"
    assert time_metadata["timeline_kind"] == "real_world"
    assert time_metadata["certainty"] == "resolved"
    assert time_metadata["anchor_timezone"] == "Asia/Shanghai"
    assert time_metadata["anchor_utc_offset"] == "+08:00"
    assert time_metadata["anchor_message_id"] == "msg_memory_scenario"
    assert time_metadata["resolved_start"] == "2026-06-03T10:00:00+08:00"
    assert time_metadata["granularity"] == "minute"
    assert len(event_links) == 1
    assert len(description_links) == 1


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


if __name__ == "__main__":
    sys.exit(main())
