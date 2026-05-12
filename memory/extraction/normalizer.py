"""Normalize extracted memory candidates into public memory records."""

from __future__ import annotations

from ..models import MemoryRecord, MemorySourceRef, MemoryTurnInput
from .schema import ExtractedMemoryCandidate


class MemoryCandidateNormalizer:
    """Convert parsed LLM candidates into generic memory records."""

    def normalize(
        self,
        candidates: list[ExtractedMemoryCandidate],
        turn: MemoryTurnInput,
    ) -> list[MemoryRecord]:
        return [self._to_record(candidate, turn) for candidate in candidates]

    def _to_record(
        self,
        candidate: ExtractedMemoryCandidate,
        turn: MemoryTurnInput,
    ) -> MemoryRecord:
        metadata = dict(candidate.metadata)
        metadata.setdefault("extracted_by", "llm")
        source_refs = self._source_refs(candidate, turn)
        return MemoryRecord(
            id=None,
            memory_type=candidate.memory_type,
            text=candidate.text,
            source_refs=source_refs,
            metadata=metadata,
        )

    def _source_refs(
        self,
        candidate: ExtractedMemoryCandidate,
        turn: MemoryTurnInput,
    ) -> list[MemorySourceRef]:
        known_message_ids = {
            message.id for message in [*turn.conversation_context, turn.new_message]
        }
        requested_ids = [
            message_id
            for message_id in candidate.source_message_ids
            if message_id in known_message_ids
        ]
        source_ids = requested_ids or [turn.new_message.id]
        return [
            MemorySourceRef(
                source_type="message",
                source_id=source_id,
                quote=candidate.source_quote,
            )
            for source_id in source_ids
        ]
