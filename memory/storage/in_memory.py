"""Process-local memory record store."""

from __future__ import annotations

from dataclasses import replace
from threading import RLock
from typing import Sequence

from ..models import MemoryRecord, MemoryRecordType
from .ids import new_memory_id


class InMemoryMemoryStore:
    """Thread-safe, process-local memory store.

    This is useful for wiring the memory runtime before a real database-backed
    memory store exists. It is intentionally not durable.
    """

    def __init__(self, records: Sequence[MemoryRecord] | None = None) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._lock = RLock()
        if records:
            self.save_records(records)

    def save_records(self, records: Sequence[MemoryRecord]) -> Sequence[MemoryRecord]:
        stored_records: list[MemoryRecord] = []
        with self._lock:
            for record in records:
                record_id = record.id or new_memory_id(record.memory_type)
                stored_record = record if record.id else replace(record, id=record_id)
                self._records[record_id] = stored_record
                stored_records.append(stored_record)
        return stored_records

    def get_records(self, record_ids: Sequence[str]) -> Sequence[MemoryRecord]:
        with self._lock:
            return [
                self._records[record_id]
                for record_id in record_ids
                if record_id in self._records
            ]

    def list_records(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        memory_type: MemoryRecordType | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        with self._lock:
            records = list(self._records.values())

        filtered = [
            record
            for record in records
            if self._matches_filters(
                record=record,
                user_id=user_id,
                session_id=session_id,
                memory_type=memory_type,
            )
        ]
        if limit is None:
            return filtered
        return filtered[: max(0, limit)]

    def clear(self) -> None:
        with self._lock:
            self._records.clear()

    def _matches_filters(
        self,
        record: MemoryRecord,
        user_id: str | None,
        session_id: str | None,
        memory_type: MemoryRecordType | None,
    ) -> bool:
        if memory_type and record.memory_type != memory_type:
            return False

        if user_id is None and session_id is None:
            return True

        record_user_id = record.metadata.get("user_id")
        record_session_id = record.metadata.get("session_id")

        if record_user_id is not None and record_user_id != user_id:
            return False
        if record_session_id is not None and record_session_id != session_id:
            return False
        return True
