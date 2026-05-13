"""Prompt construction for LLM memory extraction."""

from __future__ import annotations

import json
from typing import Any

from llm.interfaces import ChatMessageParam

from ..models import ActiveMemoryContext, MemoryRecord, MemoryTurnInput


class MemoryExtractionPromptBuilder:
    """Build the chat messages used by an LLM memory extractor."""

    def __init__(
        self,
        max_context_messages: int = 20,
        max_active_memories: int = 20,
    ) -> None:
        self.max_context_messages = max(0, max_context_messages)
        self.max_active_memories = max(0, max_active_memories)

    def build(self, turn: MemoryTurnInput) -> list[ChatMessageParam]:
        payload = {
            "timezone": turn.timezone,
            "new_message": turn.new_message.to_record(),
            "conversation_context": [
                message.to_record()
                for message in turn.conversation_context[-self.max_context_messages :]
            ],
            "context_state": (
                turn.context_state.to_record() if turn.context_state else None
            ),
            "active_memory_context": self._active_context_payload(
                turn.active_memory_context
            ),
        }
        return [
            {"role": "system", "content": self._system_prompt()},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, indent=2),
            },
        ]

    def _system_prompt(self) -> str:
        return (
            "You are the memory extraction component for a dialogue system.\n"
            "Your job is observation, not reconciliation. Extract as many durable, "
            "useful candidate facts as the latest user message and supplied context "
            "support. Do not decide whether a candidate already exists. Do not "
            "deduplicate against active memory. Do not merge, update, resolve "
            "conflicts, or decide final writes. Later memory components will do "
            "retrieval, reconciliation, merge/update, conflict handling, and storage. "
            "Use active_memory_context only to resolve references and understand "
            "meaning; never suppress a candidate just because it looks related to "
            "active memory.\n\n"
            "Return JSON only, with this aggregate shape:\n"
            "{"
            '"event_candidates":[{"client_id":"event_1","title":"short title",'
            '"summary":"optional summary","event_type":"plan|appointment|story_beat|'
            'incident|topic|other","time":{...},"descriptions":[...],"entities":[...],'
            '"source_message_ids":["msg_id"],"source_quote":"optional exact quote"}],'
            '"entity_candidates":[{"client_id":"entity_1","name":"用户",'
            '"entity_type":"person|place|organization|object|concept|animal|other",'
            '"identity_summary":"optional","aliases":[],"properties":[...],'
            '"source_message_ids":["msg_id"],"source_quote":"optional exact quote"}]'
            "}.\n\n"
            "Nested object contracts:\n"
            "- description object: {\"client_id\":\"desc_1\",\"text\":\"concrete "
            "detail\",\"description_type\":\"detail|location|outcome|other\","
            "\"time\":{...},\"source_message_ids\":[\"msg_id\"],"
            "\"source_quote\":\"exact quote\"}.\n"
            "- property object: {\"client_id\":\"prop_1\",\"text\":\"attribute or "
            "preference sentence\",\"property_type\":\"preference|habit|state|"
            "attribute|identity|other\",\"time\":{...},"
            "\"source_message_ids\":[\"msg_id\"],\"source_quote\":\"exact quote\"}.\n"
            "- entity object inside event.entities uses the same entity contract. "
            "If an involved entity also has properties, include those properties.\n\n"
            "Event candidates:\n"
            "- event is an abstract activity/topic/episode/plan/story beat, such as "
            "'会诊安排'. Do not put every detail in the title.\n"
            "- Every event must include at least one description. Example: event "
            "title '会诊安排', description '用户计划要和林医生复诊，地点在静安门诊。'.\n"
            "- If a message contains a story action or episode, output an event and "
            "description for that episode; do not output only entities.\n"
            "- Event time lives in event.time, not only in title/description.\n"
            "- event.entities should include involved entities such as 用户, 林医生, "
            "静安门诊. It is OK to output 用户 as an entity; later reconciliation "
            "will merge it with system user identity if appropriate.\n\n"
            "Plans and appointments:\n"
            "- If the latest message describes a future plan, appointment, reminder, "
            "meeting, visit, travel, task, or scheduled action, output an event. Do "
            "not output only the involved entities.\n"
            "- Example: '明天上午十点我要和林医生复诊，地点在静安的门诊' should output "
            "event title '会诊安排', a scheduled_at time for 明天上午十点, one "
            "description saying the user plans to see 林医生 at 静安门诊, and entities "
            "用户, 林医生, 静安门诊.\n\n"
            "Entity candidates:\n"
            "- entity is a person, place, object, concept, animal, organization, or "
            "other stable referent. Prefer concise normalized names such as 用户, "
            "林医生, 静安门诊, 茉莉花茶.\n"
            "- properties must be nested under the entity they describe. Do not "
            "output orphan properties.\n\n"
            "identity_summary rule:\n"
            "- identity_summary is only a short identity hint for later merge. It is "
            "not a memory fact container.\n"
            "- Never put preferences, habits, states, plans, appointments, or story "
            "details only in identity_summary. Those must become properties or "
            "event descriptions.\n"
            "- An entity with identity_summary but no properties/event descriptions "
            "is invalid when the message contains extractable facts about it.\n\n"
            "Preferences, habits, attributes, and states:\n"
            "- If the message states a preference, habit, profile fact, attribute, "
            "or current state, output it as an entity property. Do not hide it only "
            "inside identity_summary.\n"
            "- Example: '我每天早上都喝茉莉花茶，基本不喝咖啡' should output entity 用户 "
            "with properties '用户每天早上喝茉莉花茶' and '用户基本不喝咖啡'.\n"
            "- Example: '茉莉花茶最好少糖，不要加奶' should output entity 茉莉花茶 with "
            "properties '用户偏好茉莉花茶少糖' and '用户偏好茉莉花茶不加奶'.\n\n"
            "Description/property/time:\n"
            "- description is a concrete detail attached to an event.\n"
            "- property is an attribute, preference, state, habit, or profile-like "
            "fact attached to an entity.\n"
            "- time is an object nested on event, description, or property. If a "
            "nested item has the same time as its parent, use {\"role\":\"same_as_parent\"}.\n"
            "- If an item has no explicit or inferable fact time but is worth "
            "extracting, use the source message created_at as mentioned_at.\n\n"
            "Time object contract:\n"
            "- Fields: client_id, role, raw_text, time_kind, timeline_kind, "
            "certainty, anchor_timezone, anchor_utc_offset, anchor_message_id, "
            "resolved_start, resolved_end, granularity, description, duration_text, "
            "recurrence_text, source_message_ids, source_quote.\n"
            "- role must be one of occurred_at, started_at, ended_at, scheduled_at, "
            "valid_from, valid_until, mentioned_at, observed_at, recurs_at, duration, "
            "same_as_parent.\n"
            "- time_kind must be exact, relative, vague, duration, or recurring.\n"
            "- timeline_kind must be real_world or fictional.\n"
            "- certainty must be resolved, inferred, vague, or unknown.\n"
            "- exact needs resolved_start and granularity. relative needs "
            "anchor_message_id, resolved_start, and granularity. vague needs "
            "description. duration needs duration_text. recurring needs recurrence_text.\n\n"
            "Valid compact examples:\n"
            "- Input '我每天早上都喝茉莉花茶，基本不喝咖啡' => output entity 用户 with "
            "properties 用户每天早上喝茉莉花茶 and 用户基本不喝咖啡; include recurs_at or "
            "mentioned_at time links after normalization.\n"
            "- Input '明天上午十点我要和林医生复诊，地点在静安的门诊' => output event "
            "会诊安排 with scheduled_at time 明天上午十点, description 用户计划和林医生"
            "复诊且地点在静安门诊, and entities 用户, 林医生, 静安门诊.\n"
            "- Input '那只闯入铁路的鹿是在很久很久以前出现的' => output story event "
            "鹿闯入铁路 with a vague fictional time and at least one description.\n\n"
            "Rules:\n"
            "- Do not output top-level descriptions, properties, time_refs, links, "
            "time_links, create/update/ignore/conflict decisions, canonical_key, or "
            "dedup_key.\n"
            "- If nothing durable/useful should be extracted, return "
            "{\"event_candidates\":[],\"entity_candidates\":[]}."
        )

    def _active_context_payload(
        self,
        active_context: ActiveMemoryContext | None,
    ) -> dict[str, Any] | None:
        if not active_context:
            return None
        return {
            "event_memories": self._record_payload(active_context.event_memories),
            "entity_memories": self._record_payload(active_context.entity_memories),
            "property_memories": self._record_payload(active_context.property_memories),
            "other_memories": self._record_payload(active_context.other_memories),
            "last_refreshed_at_message_id": active_context.last_refreshed_at_message_id,
        }

    def _record_payload(self, records: list[MemoryRecord]) -> list[dict[str, Any]]:
        return [
            {
                "id": record.id,
                "memory_type": record.memory_type,
                "text": record.text,
                "metadata": record.metadata,
            }
            for record in records[: self.max_active_memories]
        ]
