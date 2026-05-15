"""Apply memory write plans to the process-local memory store."""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from ..interfaces import MemoryStore
from ..models import MemoryRecord
from ..reconciliation import MemoryWriteOperation
from .models import MemoryWriteFailure, MemoryWriteRequest, MemoryWriteResult

RELATION_TYPES = {"link", "time_link"}
ATTACHABLE_TYPES = {"property", "description"}


class InMemoryMemoryWritePlanApplier:
    """Apply reconciled write plans to a memory record store."""

    def __init__(self, store: MemoryStore) -> None:
        self.store = store

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
                "applier": "record_store_write_plan",
                "store": self.store.__class__.__name__,
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
            extra_metadata = self._attachment_metadata(operation, target_id)
            self._save_operation_record(
                operation=operation,
                request=request,
                state=state,
                bucket=state.attached_records,
                extra_metadata=extra_metadata,
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
        records = list(self.store.get_records([operation.existing_record_id]))
        if not records:
            self._fail(operation, "existing record was not found", state)
            return
        record = records[0]
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
        stored = list(self.store.save_records([record]))[0]
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
        metadata = dict(operation.record.metadata)
        if request.user_id is not None:
            metadata.setdefault("user_id", request.user_id)
        if request.session_id is not None:
            metadata.setdefault("session_id", request.session_id)
        metadata["write_action"] = operation.action
        metadata["write_reason"] = operation.reason
        if operation.relation_type:
            metadata.setdefault("relation_type", operation.relation_type)
        metadata.update(extra_metadata or {})
        return replace(operation.record, metadata=metadata)

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
        existing = list(self.store.get_records([candidate_or_record_id]))
        return existing[0].id if existing else None

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
