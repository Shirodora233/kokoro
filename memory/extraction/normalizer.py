"""Split aggregate extraction candidates into generic memory records."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models import MemoryRecord, MemorySourceRef, MemoryTurnInput
from .schema import (
    DescriptionCandidate,
    EntityCandidate,
    EventCandidate,
    ExtractionCandidateBatch,
    PropertyCandidate,
    SourceHint,
    TimeCandidate,
)

_UTC_OFFSET_PATTERN = re.compile(r"([+-]\d{2}:\d{2})$")


@dataclass
class _SplitState:
    sequence: int = 0
    emitted_client_ids: set[str] = field(default_factory=set)
    emitted_time_ids: set[str] = field(default_factory=set)


class MemoryCandidateNormalizer:
    """Convert aggregate candidates into current generic memory records."""

    def normalize(
        self,
        batch: ExtractionCandidateBatch,
        turn: MemoryTurnInput,
    ) -> list[MemoryRecord]:
        state = _SplitState()
        records: list[MemoryRecord] = []
        for event in batch.event_candidates:
            records.extend(self._event_records(event, turn, state))
        for entity in batch.entity_candidates:
            records.extend(self._entity_records(entity, turn, state))
        return records

    def _event_records(
        self,
        event: EventCandidate,
        turn: MemoryTurnInput,
        state: _SplitState,
    ) -> list[MemoryRecord]:
        event_id = self._candidate_id(event.client_id, "event", state)
        records: list[MemoryRecord] = []
        if event_id not in state.emitted_client_ids:
            state.emitted_client_ids.add(event_id)
            records.append(
                self._record(
                    memory_type="event",
                    text=event.title,
                    source=event.source,
                    turn=turn,
                    metadata={
                        "candidate_client_id": event_id,
                        "summary": event.summary,
                        "event_type": event.event_type,
                    },
                )
            )

        event_time_id = self._emit_time_and_link(
            records=records,
            time=event.time,
            target_client_id=event_id,
            target_type="event",
            fallback_source=event.source,
            turn=turn,
            state=state,
            default_role="mentioned_at",
        )

        for description in event.descriptions:
            records.extend(
                self._description_records(
                    description=description,
                    event_id=event_id,
                    inherited_time_id=event_time_id,
                    inherited_time_role=self._time_role(event.time, "mentioned_at"),
                    fallback_source=event.source,
                    turn=turn,
                    state=state,
                )
            )

        for entity in event.entities:
            entity_records, entity_id = self._entity_records_with_id(
                entity=entity,
                turn=turn,
                state=state,
                fallback_source=event.source,
            )
            records.extend(entity_records)
            records.append(
                self._link_record(
                    from_client_id=event_id,
                    from_type="event",
                    to_client_id=entity_id,
                    to_type="entity",
                    relation_type="involves",
                    source=event.source,
                    turn=turn,
                    state=state,
                )
            )
        return records

    def _description_records(
        self,
        description: DescriptionCandidate,
        event_id: str,
        inherited_time_id: str | None,
        inherited_time_role: str,
        fallback_source: SourceHint,
        turn: MemoryTurnInput,
        state: _SplitState,
    ) -> list[MemoryRecord]:
        description_id = self._candidate_id(description.client_id, "desc", state)
        source = self._source_or_fallback(description.source, fallback_source)
        records = [
            self._record(
                memory_type="description",
                text=description.text,
                source=source,
                turn=turn,
                metadata={
                    "candidate_client_id": description_id,
                    "event_client_id": event_id,
                    "description_type": description.description_type,
                },
            ),
            self._link_record(
                from_client_id=event_id,
                from_type="event",
                to_client_id=description_id,
                to_type="description",
                relation_type="has_description",
                source=source,
                turn=turn,
                state=state,
            ),
        ]

        if description.time and description.time.role != "same_as_parent":
            self._emit_time_and_link(
                records=records,
                time=description.time,
                target_client_id=description_id,
                target_type="description",
                fallback_source=source,
                turn=turn,
                state=state,
                default_role="mentioned_at",
            )
        elif inherited_time_id:
            records.append(
                self._time_link_record(
                    target_client_id=description_id,
                    target_type="description",
                    time_ref_client_id=inherited_time_id,
                    time_role=inherited_time_role,
                    source=source,
                    turn=turn,
                    state=state,
                )
            )
        return records

    def _entity_records(
        self,
        entity: EntityCandidate,
        turn: MemoryTurnInput,
        state: _SplitState,
    ) -> list[MemoryRecord]:
        records, _ = self._entity_records_with_id(entity, turn, state)
        return records

    def _entity_records_with_id(
        self,
        entity: EntityCandidate,
        turn: MemoryTurnInput,
        state: _SplitState,
        fallback_source: SourceHint | None = None,
    ) -> tuple[list[MemoryRecord], str]:
        entity_id = self._candidate_id(entity.client_id, "entity", state)
        source = self._source_or_fallback(entity.source, fallback_source)
        records: list[MemoryRecord] = []
        if entity_id not in state.emitted_client_ids:
            state.emitted_client_ids.add(entity_id)
            records.append(
                self._record(
                    memory_type="entity",
                    text=entity.name,
                    source=source,
                    turn=turn,
                    metadata={
                        "candidate_client_id": entity_id,
                        "entity_type": entity.entity_type,
                        "identity_summary": entity.identity_summary,
                        "aliases": entity.aliases,
                    },
                )
            )

        for prop in entity.properties:
            records.extend(
                self._property_records(
                    prop=prop,
                    entity_id=entity_id,
                    fallback_source=source,
                    turn=turn,
                    state=state,
                )
            )
        return records, entity_id

    def _property_records(
        self,
        prop: PropertyCandidate,
        entity_id: str,
        fallback_source: SourceHint,
        turn: MemoryTurnInput,
        state: _SplitState,
    ) -> list[MemoryRecord]:
        property_id = self._candidate_id(prop.client_id, "prop", state)
        source = self._source_or_fallback(prop.source, fallback_source)
        records = [
            self._record(
                memory_type="property",
                text=prop.text,
                source=source,
                turn=turn,
                metadata={
                    "candidate_client_id": property_id,
                    "entity_client_id": entity_id,
                    "property_type": prop.property_type,
                },
            ),
            self._link_record(
                from_client_id=entity_id,
                from_type="entity",
                to_client_id=property_id,
                to_type="property",
                relation_type="has_property",
                source=source,
                turn=turn,
                state=state,
            ),
        ]
        self._emit_time_and_link(
            records=records,
            time=prop.time,
            target_client_id=property_id,
            target_type="property",
            fallback_source=source,
            turn=turn,
            state=state,
            default_role="mentioned_at",
        )
        return records

    def _emit_time_and_link(
        self,
        records: list[MemoryRecord],
        time: TimeCandidate | None,
        target_client_id: str,
        target_type: str,
        fallback_source: SourceHint,
        turn: MemoryTurnInput,
        state: _SplitState,
        default_role: str,
    ) -> str | None:
        time_ref = time or self._mentioned_time(turn, fallback_source, state)
        if time_ref.role == "same_as_parent":
            return None

        time_id = self._time_id(time_ref, state)
        if time_id not in state.emitted_time_ids:
            state.emitted_time_ids.add(time_id)
            records.append(self._time_record(time_ref, time_id, fallback_source, turn))
        records.append(
            self._time_link_record(
                target_client_id=target_client_id,
                target_type=target_type,
                time_ref_client_id=time_id,
                time_role=self._time_role(time_ref, default_role),
                source=self._source_or_fallback(time_ref.source, fallback_source),
                turn=turn,
                state=state,
            )
        )
        return time_id

    def _time_record(
        self,
        time: TimeCandidate,
        time_id: str,
        fallback_source: SourceHint,
        turn: MemoryTurnInput,
    ) -> MemoryRecord:
        metadata = self._time_metadata(time, turn, fallback_source)
        metadata["candidate_client_id"] = time_id
        return self._record(
            memory_type="time_ref",
            text=time.raw_text or time.description or time.duration_text or "mentioned time",
            source=self._source_or_fallback(time.source, fallback_source),
            turn=turn,
            metadata=metadata,
        )

    def _time_link_record(
        self,
        target_client_id: str,
        target_type: str,
        time_ref_client_id: str,
        time_role: str,
        source: SourceHint,
        turn: MemoryTurnInput,
        state: _SplitState,
    ) -> MemoryRecord:
        link_id = self._candidate_id(None, "time_link", state)
        return self._record(
            memory_type="time_link",
            text=f"{target_type} {target_client_id} {time_role} {time_ref_client_id}",
            source=source,
            turn=turn,
            metadata={
                "candidate_client_id": link_id,
                "target_client_id": target_client_id,
                "target_type": target_type,
                "time_ref_client_id": time_ref_client_id,
                "time_role": time_role,
            },
        )

    def _link_record(
        self,
        from_client_id: str,
        from_type: str,
        to_client_id: str,
        to_type: str,
        relation_type: str,
        source: SourceHint,
        turn: MemoryTurnInput,
        state: _SplitState,
    ) -> MemoryRecord:
        link_id = self._candidate_id(None, "link", state)
        return self._record(
            memory_type="link",
            text=f"{from_type} {from_client_id} {relation_type} {to_type} {to_client_id}",
            source=source,
            turn=turn,
            metadata={
                "candidate_client_id": link_id,
                "from_client_id": from_client_id,
                "from_type": from_type,
                "to_client_id": to_client_id,
                "to_type": to_type,
                "relation_type": relation_type,
            },
        )

    def _record(
        self,
        memory_type: str,
        text: str,
        source: SourceHint,
        turn: MemoryTurnInput,
        metadata: dict[str, Any],
    ) -> MemoryRecord:
        cleaned_metadata = {
            key: value for key, value in metadata.items() if value not in (None, [], {})
        }
        cleaned_metadata.setdefault("extracted_by", "llm")
        return MemoryRecord(
            id=None,
            memory_type=memory_type,
            text=text,
            source_refs=self._source_refs(source, turn),
            metadata=cleaned_metadata,
        )

    def _source_refs(
        self,
        source: SourceHint,
        turn: MemoryTurnInput,
    ) -> list[MemorySourceRef]:
        known_message_ids = {
            message.id for message in [*turn.conversation_context, turn.new_message]
        }
        message_content = {
            message.id: message.content
            for message in [*turn.conversation_context, turn.new_message]
        }
        requested_ids = [
            message_id
            for message_id in source.source_message_ids
            if message_id in known_message_ids
        ]
        source_ids = requested_ids or [turn.new_message.id]
        return [
            MemorySourceRef(
                source_type="message",
                source_id=source_id,
                quote=self._quote_for_source(source.source_quote, source_id, message_content),
            )
            for source_id in source_ids
        ]

    def _mentioned_time(
        self,
        turn: MemoryTurnInput,
        source: SourceHint,
        state: _SplitState,
    ) -> TimeCandidate:
        message_id = (
            source.source_message_ids[0]
            if source.source_message_ids
            else turn.new_message.id
        )
        created_at = self._message_created_at(turn, message_id) or turn.new_message.created_at
        return TimeCandidate(
            client_id=self._candidate_id(None, "time", state),
            role="mentioned_at",
            raw_text=created_at or "message mention time",
            time_kind="exact" if created_at else "vague",
            timeline_kind="real_world",
            certainty="resolved" if created_at else "unknown",
            anchor_timezone=turn.timezone or "UTC",
            anchor_utc_offset=self._utc_offset(created_at) or "+00:00",
            resolved_start=created_at,
            granularity="second" if created_at else None,
            description=None if created_at else "The source message mention time.",
            source=source,
        )

    def _time_metadata(
        self,
        time: TimeCandidate,
        turn: MemoryTurnInput,
        fallback_source: SourceHint,
    ) -> dict[str, Any]:
        metadata = dict(time.metadata)
        for field_name in [
            "raw_text",
            "time_kind",
            "timeline_kind",
            "certainty",
            "anchor_timezone",
            "anchor_utc_offset",
            "anchor_message_id",
            "resolved_start",
            "resolved_end",
            "granularity",
            "description",
            "duration_text",
            "recurrence_text",
        ]:
            value = getattr(time, field_name)
            if value is not None:
                metadata.setdefault(field_name, value)
        metadata.setdefault("raw_text", self._time_raw_text(time))
        metadata.setdefault("time_kind", self._infer_time_kind(time))
        metadata.setdefault("timeline_kind", time.timeline_kind or "real_world")
        metadata.setdefault("certainty", time.certainty or "unknown")
        metadata.setdefault("anchor_timezone", turn.timezone or "UTC")
        metadata.setdefault(
            "anchor_utc_offset",
            self._source_utc_offset(turn, self._source_or_fallback(time.source, fallback_source))
            or "+00:00",
        )
        self._fill_kind_specific_time_metadata(metadata)
        return metadata

    def _time_raw_text(self, time: TimeCandidate) -> str:
        return (
            time.raw_text
            or time.description
            or time.duration_text
            or time.recurrence_text
            or "message mention time"
        )

    def _infer_time_kind(self, time: TimeCandidate) -> str:
        if time.time_kind:
            return time.time_kind
        if time.duration_text:
            return "duration"
        if time.recurrence_text:
            return "recurring"
        if time.resolved_start:
            return "exact"
        return "vague"

    def _fill_kind_specific_time_metadata(self, metadata: dict[str, Any]) -> None:
        time_kind = metadata.get("time_kind")
        raw_text = metadata.get("raw_text")
        if time_kind == "vague" and not metadata.get("description"):
            metadata["description"] = raw_text or "Vague time expression."
        if time_kind == "duration" and not metadata.get("duration_text"):
            metadata["duration_text"] = raw_text or "Duration expression."
        if time_kind == "recurring" and not metadata.get("recurrence_text"):
            metadata["recurrence_text"] = raw_text or "Recurring time expression."

    def _time_role(self, time: TimeCandidate | None, default_role: str) -> str:
        if time and time.role and time.role != "same_as_parent":
            return time.role
        return default_role

    def _time_id(self, time: TimeCandidate, state: _SplitState) -> str:
        return self._candidate_id(time.client_id, "time", state)

    def _candidate_id(
        self,
        client_id: str | None,
        prefix: str,
        state: _SplitState,
    ) -> str:
        if client_id:
            return client_id
        state.sequence += 1
        return f"{prefix}_{state.sequence}"

    def _source_or_fallback(
        self,
        source: SourceHint,
        fallback: SourceHint | None,
    ) -> SourceHint:
        if source.source_message_ids or source.source_quote:
            return source
        return fallback or source

    def _quote_for_source(
        self,
        quote: str | None,
        source_id: str,
        message_content: dict[str, str],
    ) -> str | None:
        if not quote:
            return None
        if quote in message_content.get(source_id, ""):
            return quote
        return None

    def _message_created_at(
        self,
        turn: MemoryTurnInput,
        message_id: str,
    ) -> str | None:
        for message in [*turn.conversation_context, turn.new_message]:
            if message.id == message_id:
                return message.created_at
        return None

    def _utc_offset(self, created_at: str | None) -> str | None:
        if not created_at:
            return None
        match = _UTC_OFFSET_PATTERN.search(created_at)
        return match.group(1) if match else None

    def _source_utc_offset(self, turn: MemoryTurnInput, source: SourceHint) -> str | None:
        for message_id in source.source_message_ids:
            created_at = self._message_created_at(turn, message_id)
            offset = self._utc_offset(created_at)
            if offset:
                return offset
        return self._utc_offset(turn.new_message.created_at)
