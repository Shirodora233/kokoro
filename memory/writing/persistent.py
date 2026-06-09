"""Apply memory write plans directly to durable normalized persistence."""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from ..models import MemoryRecord
from ..persistence import (
    MemoryRecordPersistenceAdapter,
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentMemoryBundle,
    PersistentMemoryRepository,
    PersistentProperty,
    PersistentTimeLink,
    PersistentTimeRef,
)
from ..reconciliation import MemoryWriteOperation
from ..storage.ids import new_memory_id
from .models import MemoryWriteFailure, MemoryWriteRequest, MemoryWriteResult

RELATION_TYPES = {"link", "time_link"}
ATTACHABLE_TYPES = {"property", "description"}


class PersistentMemoryWritePlanApplier:
    """Apply reconciled write plans to normalized durable memory tables."""

    def __init__(
        self,
        repository: PersistentMemoryRepository,
        adapter: MemoryRecordPersistenceAdapter | None = None,
    ) -> None:
        self.repository = repository
        self.adapter = adapter or MemoryRecordPersistenceAdapter()

    def apply(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        state = _ApplyState()
        operations = list(request.plan.operations)

        self._apply_reuse_ignore_conflicts(operations, state)
        self._apply_creates(operations, request, state)
        self._apply_attached_records(operations, request, state)
        self._apply_relation_records(operations, request, state)

        return MemoryWriteResult(
            created_records=state.created_records,
            reused_records=state.reused_records,
            attached_records=state.attached_records,
            ignored_operations=state.ignored_operations,
            conflict_operations=state.conflict_operations,
            failed_operations=state.failed_operations,
            candidate_record_ids=dict(state.candidate_record_ids),
            metadata={
                "applier": "persistent_write_plan",
                "repository": self.repository.__class__.__name__,
                "operation_count": len(operations),
                "created_count": len(state.created_records),
                "reused_count": len(state.reused_records),
                "attached_count": len(state.attached_records),
                "failed_count": len(state.failed_operations),
            },
        )

    def _apply_reuse_ignore_conflicts(
        self,
        operations: Sequence[MemoryWriteOperation],
        state: "_ApplyState",
    ) -> None:
        for operation in operations:
            if operation.action == "reuse":
                self._apply_reuse(operation, state)
            elif operation.action == "ignore":
                state.ignored_operations.append(operation)
                self._map_existing_candidate(operation, state)
            elif operation.action == "flag_conflict":
                state.conflict_operations.append(operation)

    def _apply_creates(
        self,
        operations: Sequence[MemoryWriteOperation],
        request: MemoryWriteRequest,
        state: "_ApplyState",
    ) -> None:
        for operation in operations:
            if operation.action != "create":
                continue
            if operation.candidate_type in RELATION_TYPES | ATTACHABLE_TYPES:
                continue
            existing_record = self._same_plan_record(operation, state)
            if existing_record is not None:
                state.reused_records.append(existing_record)
                self._map_candidate(operation, existing_record, state)
                continue
            self._save_operation_record(
                operation=operation,
                request=request,
                state=state,
                bucket=state.created_records,
            )

    def _apply_attached_records(
        self,
        operations: Sequence[MemoryWriteOperation],
        request: MemoryWriteRequest,
        state: "_ApplyState",
    ) -> None:
        for operation in operations:
            if operation.candidate_type not in ATTACHABLE_TYPES:
                continue
            if operation.action not in {"attach", "create"}:
                continue
            target_id = self._target_record_id(operation, state)
            if operation.action == "attach" and not target_id:
                self._fail(operation, "attach target could not be resolved", state)
                continue
            self._save_operation_record(
                operation=operation,
                request=request,
                state=state,
                bucket=state.attached_records,
                extra_metadata=self._attachment_metadata(operation, target_id),
            )

    def _apply_relation_records(
        self,
        operations: Sequence[MemoryWriteOperation],
        request: MemoryWriteRequest,
        state: "_ApplyState",
    ) -> None:
        for operation in operations:
            if operation.candidate_type not in RELATION_TYPES:
                continue
            if operation.action not in {"attach", "create"}:
                continue
            endpoint_metadata = self._relation_endpoint_metadata(operation, state)
            if endpoint_metadata is None:
                self._fail(operation, "relation endpoints could not be resolved", state)
                continue
            self._save_operation_record(
                operation=operation,
                request=request,
                state=state,
                bucket=state.attached_records,
                extra_metadata=endpoint_metadata,
            )

    def _apply_reuse(
        self,
        operation: MemoryWriteOperation,
        state: "_ApplyState",
    ) -> None:
        if not operation.existing_record_id:
            self._fail(operation, "reuse operation has no existing_record_id", state)
            return
        record = self._get_record(operation.existing_record_id)
        if record is None:
            self._fail(operation, "existing record was not found", state)
            return
        state.reused_records.append(record)
        self._map_candidate(operation, record, state)

    def _save_operation_record(
        self,
        operation: MemoryWriteOperation,
        request: MemoryWriteRequest,
        state: "_ApplyState",
        bucket: list[MemoryRecord],
        extra_metadata: dict[str, object] | None = None,
    ) -> None:
        if operation.record is None:
            self._fail(operation, "operation has no record to save", state)
            return
        record = self._record_for_write(operation, request, extra_metadata)
        build_result = self.adapter.build_bundle([record])
        if build_result.skipped_records:
            reason = "; ".join(item.reason for item in build_result.skipped_records)
            self._fail(operation, reason or "record could not be persisted", state)
            return
        stored_bundle = self.repository.save_bundle(build_result.bundle)
        stored = self._stored_record(record, stored_bundle)
        if stored is None:
            self._fail(operation, "repository returned no stored object", state)
            return
        bucket.append(stored)
        self._map_candidate(operation, stored, state)
        self._remember_same_plan_record(stored, state)

    def _record_for_write(
        self,
        operation: MemoryWriteOperation,
        request: MemoryWriteRequest,
        extra_metadata: dict[str, object] | None,
    ) -> MemoryRecord:
        assert operation.record is not None
        record_id = operation.record.id or new_memory_id(operation.record.memory_type)
        metadata = dict(operation.record.metadata)
        if request.user_id is not None:
            metadata.setdefault("user_id", request.user_id)
        if request.session_id is not None:
            metadata.setdefault("session_id", request.session_id)
        for key in (
            "created_turn_id",
            "created_checkpoint_id",
            "created_checkpoint_sequence",
        ):
            if key in request.metadata:
                metadata.setdefault(key, request.metadata[key])
        metadata["write_action"] = operation.action
        metadata["write_reason"] = operation.reason
        if operation.relation_type:
            metadata.setdefault("relation_type", operation.relation_type)
        metadata.update(extra_metadata or {})
        return replace(operation.record, id=record_id, metadata=metadata)

    def _target_record_id(
        self,
        operation: MemoryWriteOperation,
        state: "_ApplyState",
    ) -> str | None:
        if operation.target_record_id:
            return operation.target_record_id
        if operation.target_candidate_id:
            return state.candidate_record_ids.get(operation.target_candidate_id)
        return None

    def _attachment_metadata(
        self,
        operation: MemoryWriteOperation,
        target_id: str | None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {}
        if target_id:
            metadata["attached_to_record_id"] = target_id
        if operation.target_candidate_id:
            metadata["attached_to_candidate_id"] = operation.target_candidate_id
        if operation.relation_type:
            metadata["attached_relation_type"] = operation.relation_type
        return metadata

    def _relation_endpoint_metadata(
        self,
        operation: MemoryWriteOperation,
        state: "_ApplyState",
    ) -> dict[str, object] | None:
        if operation.record is None:
            return None
        metadata: dict[str, object] = {}
        endpoint_keys = {
            "from_client_id": "from_record_id",
            "to_client_id": "to_record_id",
            "target_client_id": "target_record_id",
            "time_ref_client_id": "time_ref_record_id",
        }
        for client_key, record_key in endpoint_keys.items():
            raw_value = operation.record.metadata.get(client_key)
            if not isinstance(raw_value, str):
                continue
            record_id = self._resolve_record_id(raw_value, state)
            if not record_id:
                return None
            metadata[record_key] = record_id
        return metadata

    def _resolve_record_id(
        self,
        candidate_or_record_id: str,
        state: "_ApplyState",
    ) -> str | None:
        mapped = state.candidate_record_ids.get(candidate_or_record_id)
        if mapped:
            return mapped
        existing = self._get_record(candidate_or_record_id)
        return existing.id if existing else None

    def _get_record(self, record_id: str) -> MemoryRecord | None:
        loaders = (
            self.repository.get_event,
            self.repository.get_description,
            self.repository.get_entity,
            self.repository.get_property,
            self.repository.get_link,
            self.repository.get_time_ref,
            self.repository.get_time_link,
        )
        for loader in loaders:
            item = loader(record_id)
            record = _persistent_to_record(item)
            if record is not None:
                return record
        return None

    def _stored_record(
        self,
        original: MemoryRecord,
        bundle: PersistentMemoryBundle,
    ) -> MemoryRecord | None:
        if original.memory_type == "event" and bundle.events:
            return _persistent_to_record(bundle.events[0])
        if original.memory_type == "description" and bundle.descriptions:
            return _persistent_to_record(bundle.descriptions[0])
        if original.memory_type == "entity" and bundle.entities:
            return _persistent_to_record(bundle.entities[0])
        if original.memory_type == "property" and bundle.properties:
            return _persistent_to_record(bundle.properties[0])
        if original.memory_type == "link" and bundle.links:
            return _persistent_to_record(bundle.links[0])
        if original.memory_type == "time_ref" and bundle.time_refs:
            return _persistent_to_record(bundle.time_refs[0])
        if original.memory_type == "time_link" and bundle.time_links:
            return _persistent_to_record(bundle.time_links[0])
        return None

    def _map_existing_candidate(
        self,
        operation: MemoryWriteOperation,
        state: "_ApplyState",
    ) -> None:
        if operation.candidate_id and operation.existing_record_id:
            state.candidate_record_ids[operation.candidate_id] = (
                operation.existing_record_id
            )

    def _map_candidate(
        self,
        operation: MemoryWriteOperation,
        record: MemoryRecord,
        state: "_ApplyState",
    ) -> None:
        if operation.candidate_id and record.id:
            state.candidate_record_ids[operation.candidate_id] = record.id

    def _same_plan_record(
        self,
        operation: MemoryWriteOperation,
        state: "_ApplyState",
    ) -> MemoryRecord | None:
        if operation.record is None:
            return None
        key = self._same_plan_key(operation.record)
        if key is None:
            return None
        return state.same_plan_records.get(key)

    def _remember_same_plan_record(
        self,
        record: MemoryRecord,
        state: "_ApplyState",
    ) -> None:
        key = self._same_plan_key(record)
        if key is not None:
            state.same_plan_records.setdefault(key, record)

    def _same_plan_key(self, record: MemoryRecord) -> tuple[object, ...] | None:
        if record.memory_type != "time_ref":
            return None
        metadata = record.metadata
        time_kind = metadata.get("time_kind")
        timeline_kind = metadata.get("timeline_kind")
        timezone = metadata.get("anchor_timezone")
        if time_kind in {"exact", "relative"}:
            resolved_start = metadata.get("resolved_start")
            if not isinstance(resolved_start, str) or not resolved_start.strip():
                return None
            return (
                "time_ref",
                time_kind,
                timeline_kind,
                timezone,
                resolved_start,
                metadata.get("resolved_end"),
                metadata.get("granularity"),
            )
        if time_kind == "recurring":
            recurrence_text = metadata.get("recurrence_text")
            if isinstance(recurrence_text, str) and recurrence_text.strip():
                return ("time_ref", time_kind, timeline_kind, timezone, recurrence_text)
        if time_kind == "duration":
            duration_text = metadata.get("duration_text")
            if isinstance(duration_text, str) and duration_text.strip():
                return ("time_ref", time_kind, timeline_kind, timezone, duration_text)
        return None

    def _fail(
        self,
        operation: MemoryWriteOperation,
        reason: str,
        state: "_ApplyState",
    ) -> None:
        state.failed_operations.append(MemoryWriteFailure(operation, reason))


class _ApplyState:
    def __init__(self) -> None:
        self.created_records: list[MemoryRecord] = []
        self.reused_records: list[MemoryRecord] = []
        self.attached_records: list[MemoryRecord] = []
        self.ignored_operations: list[MemoryWriteOperation] = []
        self.conflict_operations: list[MemoryWriteOperation] = []
        self.failed_operations: list[MemoryWriteFailure] = []
        self.candidate_record_ids: dict[str, str] = {}
        self.same_plan_records: dict[tuple[object, ...], MemoryRecord] = {}


def _persistent_to_record(item: object | None) -> MemoryRecord | None:
    if isinstance(item, PersistentEvent):
        return MemoryRecord(
            id=item.id,
            memory_type="event",
            text=item.title,
            source_refs=[],
            metadata={
                **dict(item.metadata),
                "summary": item.summary,
                "event_type": item.event_type,
                "user_id": item.user_id,
                "session_id": item.session_id,
                "confidence": item.confidence,
                "importance": item.importance,
            },
        )
    if isinstance(item, PersistentDescription):
        return MemoryRecord(
            id=item.id,
            memory_type="description",
            text=item.content,
            source_refs=[],
            metadata={
                **dict(item.metadata),
                "attached_to_record_id": item.event_id,
                "description_type": item.description_type,
                "user_id": item.user_id,
                "session_id": item.session_id,
                "confidence": item.confidence,
                "importance": item.importance,
            },
        )
    if isinstance(item, PersistentEntity):
        return MemoryRecord(
            id=item.id,
            memory_type="entity",
            text=item.name,
            source_refs=[],
            metadata={
                **dict(item.metadata),
                "entity_type": item.entity_type,
                "identity_summary": item.identity_summary,
                "aliases": list(item.aliases),
                "user_id": item.user_id,
                "session_id": item.session_id,
                "scope": item.scope,
                "confidence": item.confidence,
                "importance": item.importance,
            },
        )
    if isinstance(item, PersistentProperty):
        return MemoryRecord(
            id=item.id,
            memory_type="property",
            text=item.content,
            source_refs=[],
            metadata={
                **dict(item.metadata),
                "attached_to_record_id": item.entity_id,
                "property_type": item.property_type,
                "user_id": item.user_id,
                "session_id": item.session_id,
                "confidence": item.confidence,
                "importance": item.importance,
            },
        )
    if isinstance(item, PersistentLink):
        return MemoryRecord(
            id=item.id,
            memory_type="link",
            text=f"{item.from_ref.object_type} {item.relation_type} {item.to_ref.object_type}",
            source_refs=[],
            metadata={
                **dict(item.metadata),
                "from_type": item.from_ref.object_type,
                "from_record_id": item.from_ref.object_id,
                "to_type": item.to_ref.object_type,
                "to_record_id": item.to_ref.object_id,
                "relation_type": item.relation_type,
                "confidence": item.confidence,
            },
        )
    if isinstance(item, PersistentTimeRef):
        return MemoryRecord(
            id=item.id,
            memory_type="time_ref",
            text=item.raw_text,
            source_refs=[],
            metadata={
                **dict(item.metadata),
                "raw_text": item.raw_text,
                "time_kind": item.time_kind,
                "timeline_kind": item.timeline_kind,
                "certainty": item.certainty,
                "anchor_timezone": item.anchor_timezone,
                "anchor_utc_offset": item.anchor_utc_offset,
                "anchor_message_id": item.anchor_message_id,
                "resolved_start": item.resolved_start,
                "resolved_end": item.resolved_end,
                "granularity": item.granularity,
                "description": item.description,
                "duration_text": item.duration_text,
                "recurrence_text": item.recurrence_text,
            },
        )
    if isinstance(item, PersistentTimeLink):
        return MemoryRecord(
            id=item.id,
            memory_type="time_link",
            text=f"{item.target_ref.object_type} {item.time_role} time_ref",
            source_refs=[],
            metadata={
                **dict(item.metadata),
                "target_type": item.target_ref.object_type,
                "target_record_id": item.target_ref.object_id,
                "time_ref_record_id": item.time_ref_id,
                "time_role": item.time_role,
                "confidence": item.confidence,
            },
        )
    return None
