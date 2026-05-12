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
            "Return JSON only, with this shape:\n"
            '{"memories":[{"client_id":"local_id","memory_type":"entity|event|'
            'description|property|link|time_ref|time_link|summary","text":"concise '
            'standalone memory","metadata":{},"source_message_ids":["msg_id"],'
            '"source_quote":"optional exact quote"}]}.\n\n'
            "Concepts:\n"
            "- event: a durable topic, episode, plan, appointment, story beat, or "
            "larger contextual unit. Do not use event for every small detail. Every "
            "event must have an independent time_ref plus a time_link.\n"
            "- description: a concrete detail, observation, or small fact about an "
            "entity/event/topic. If a description has important timing, extract a "
            "separate time_ref and time_link instead of putting the time inside the "
            "description text.\n"
            "- entity: a person, place, object, concept, story entity, or other "
            "stable referent. If identity is ambiguous, put identity_summary in "
            "metadata as a short natural-language phrase.\n"
            "- property: an attribute, preference, state, habit, constraint, or "
            "profile-like fact.\n"
            "- time_ref: an independent time object. Extract explicit, relative, "
            "vague, duration, recurring, and fictional times as time_ref records. "
            "Do not bury time only inside event or description text.\n"
            "- time_link: links a time_ref to an event, description, property, "
            "entity, or summary.\n\n"
            "Time contract:\n"
            "- Each time_ref metadata must include raw_text, time_kind, "
            "timeline_kind, certainty, anchor_timezone, and anchor_utc_offset.\n"
            "- time_kind must be one of exact, relative, vague, duration, recurring.\n"
            "- timeline_kind must be real_world or fictional.\n"
            "- certainty must be resolved, inferred, vague, or unknown.\n"
            "- exact time_ref also needs resolved_start and granularity.\n"
            "- relative time_ref also needs anchor_message_id, resolved_start, and "
            "granularity. Use the message created_at plus the supplied timezone to "
            "resolve relative real-world time when possible.\n"
            "- vague time_ref also needs description.\n"
            "- duration time_ref also needs duration_text.\n"
            "- recurring time_ref also needs recurrence_text.\n"
            "- Fictional times still need anchor_timezone and anchor_utc_offset to "
            "record the interpretation context, but their timeline_kind must be "
            "fictional.\n"
            "- Each time_link metadata must include target_client_id, "
            "time_ref_client_id, and time_role. time_role must be one of "
            "occurred_at, started_at, ended_at, scheduled_at, valid_from, "
            "valid_until, mentioned_at, duration.\n\n"
            "Rules:\n"
            "- Give every memory a unique client_id so time_link can refer to it.\n"
            "- If you output an event, also output a valid time_ref and a time_link "
            "that links the event client_id to that time_ref client_id.\n"
            "- If an event has no explicit or inferable event time but is still "
            "worth extracting, create a time_ref for when it was mentioned and use "
            "time_role=mentioned_at.\n"
            "- Prefer keeping event/description text free of detailed time wording; "
            "put the time in time_ref.\n"
            "- It is acceptable to output candidates that may duplicate existing "
            "active memory. Do not mark create/update/ignore/conflict.\n"
            "- Do not output canonical_key or dedup_key.\n"
            "If nothing should be remembered, return {\"memories\":[]}."
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
