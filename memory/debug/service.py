"""Read-only debug service for memory state and traces."""

from __future__ import annotations

from typing import Any

from ..interfaces import MemoryStore
from ..persistence import PersistentMemoryRepository, PersistentObjectRef
from .recorder import MemoryDebugRecorder


class MemoryDebugService:
    """Aggregate current memory state and process-local debug traces."""

    def __init__(
        self,
        recorder: MemoryDebugRecorder,
        memory_store: MemoryStore | None = None,
        active_cache: Any | None = None,
        persistent_repository: PersistentMemoryRepository | None = None,
    ) -> None:
        self.recorder = recorder
        self.memory_store = memory_store
        self.active_cache = active_cache
        self.persistent_repository = persistent_repository

    def memory_snapshot(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        selected_limit = max(0, limit)
        generic_records = self._generic_records(
            user_id=user_id,
            session_id=session_id,
            limit=selected_limit,
        )
        active_context = (
            self.active_cache.get(user_id=user_id, session_id=session_id)
            if self.active_cache is not None
            else None
        )
        return {
            "debug": {
                "enabled": self.recorder.enabled,
                "max_traces": self.recorder.max_traces,
                "max_raw_chars": self.recorder.max_raw_chars,
            },
            "scope": {
                "user_id": user_id,
                "session_id": session_id,
                "limit": selected_limit,
            },
            "generic_memories": [record.to_record() for record in generic_records],
            "active_memory_context": (
                active_context.to_record() if active_context is not None else None
            ),
            "normalized_memories": self._normalized_snapshot(
                user_id=user_id,
                session_id=session_id,
                limit=selected_limit,
            ),
        }

    def trace_summaries(
        self,
        session_id: str | None = None,
        message_id: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return [
            trace.to_summary_record()
            for trace in self.recorder.list_traces(
                session_id=session_id,
                message_id=message_id,
                limit=limit,
            )
        ]

    def trace(
        self,
        trace_id: str,
        include_raw: bool = False,
    ) -> dict[str, Any] | None:
        trace = self.recorder.get(trace_id)
        return trace.to_record(include_raw=include_raw) if trace else None

    def _generic_records(
        self,
        user_id: str | None,
        session_id: str | None,
        limit: int,
    ):
        if self.memory_store is None:
            return []
        return self.memory_store.list_records(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )

    def _normalized_snapshot(
        self,
        user_id: str | None,
        session_id: str | None,
        limit: int,
    ) -> dict[str, Any] | None:
        repository = self.persistent_repository
        if repository is None:
            return None

        events = repository.list_events(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )
        entities = repository.list_entities(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )
        descriptions = repository.list_descriptions(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )
        properties = repository.list_properties(
            user_id=user_id,
            session_id=session_id,
            limit=limit,
        )
        object_refs = [
            *[
                PersistentObjectRef("event", item.id)
                for item in events
                if item.id
            ],
            *[
                PersistentObjectRef("description", item.id)
                for item in descriptions
                if item.id
            ],
            *[
                PersistentObjectRef("entity", item.id)
                for item in entities
                if item.id
            ],
            *[
                PersistentObjectRef("property", item.id)
                for item in properties
                if item.id
            ],
        ]
        links = repository.list_links(
            object_refs=object_refs,
            user_id=user_id,
            limit=limit,
        )
        time_links = repository.list_time_links(
            target_refs=object_refs,
            limit=limit,
        )
        time_refs = repository.get_time_refs(
            [
                time_link.time_ref_id
                for time_link in time_links
                if time_link.time_ref_id
            ]
        )
        return {
            "events": [item.to_record() for item in events],
            "descriptions": [item.to_record() for item in descriptions],
            "entities": [item.to_record() for item in entities],
            "properties": [item.to_record() for item in properties],
            "links": [item.to_record() for item in links],
            "time_links": [item.to_record() for item in time_links],
            "time_refs": [item.to_record() for item in time_refs],
        }
