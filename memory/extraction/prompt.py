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
            "Extract only durable, useful memory candidates from the user's latest "
            "message and the supplied context.\n"
            "Return JSON only, with this shape: "
            '{"memories":[{"memory_type":"entity|event|description|property|link|'
            'time_ref|time_link|summary","text":"concise standalone memory",'
            '"metadata":{},"source_message_ids":["msg_id"],"source_quote":"optional"}]}.\n'
            "Use event for active topics or larger contextual units, not every small "
            "incident. Use description for concrete details or small facts. Use "
            "entity for people, places, objects, concepts, or story entities. Use "
            "property for attributes/preferences/states. Use time_ref for explicit, "
            "relative, vague, or fictional time expressions.\n"
            "Do not output canonical_key or dedup_key. If an entity needs identity "
            "help, put a short natural-language identity_summary inside metadata.\n"
            "Use the provided timezone when interpreting relative real-world time. "
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
