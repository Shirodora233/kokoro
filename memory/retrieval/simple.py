"""Simple in-memory retrieval and rendering."""

from __future__ import annotations

from typing import Sequence

from ..interfaces import MemoryContextRenderer
from ..models import (
    ActiveMemoryContext,
    MemoryContextBlock,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
)
from ..storage import InMemoryMemoryStore


class SimpleMemoryContextRenderer:
    """Render memory records into a compact prompt block."""

    def render(self, records: Sequence[MemoryRecord]) -> Sequence[MemoryContextBlock]:
        visible_records = [record for record in records if record.text.strip()]
        if not visible_records:
            return []

        lines = [
            f"- ({record.memory_type}) {record.text.strip()}"
            for record in visible_records
        ]
        source_ids = [
            record.id
            for record in visible_records
            if record.id is not None
        ]
        return [
            MemoryContextBlock(
                content="Relevant memories:\n" + "\n".join(lines),
                kind="long_term_memory",
                source_memory_ids=source_ids,
                priority=10,
            )
        ]


class InMemoryMemoryRetriever:
    """Scope-aware retrieval over the process-local memory store."""

    def __init__(
        self,
        store: InMemoryMemoryStore,
        renderer: MemoryContextRenderer | None = None,
        default_limit: int = 8,
    ) -> None:
        self.store = store
        self.renderer = renderer or SimpleMemoryContextRenderer()
        self.default_limit = default_limit

    def retrieve(self, request: MemoryRetrievalRequest) -> MemoryRetrievalResult:
        active_records = self._records_from_active_context(request.active_memory_context)
        stored_records = self.store.list_records(
            user_id=request.user_id,
            session_id=request.session_id,
        )
        records = self._dedupe([*active_records, *stored_records])

        if request.query:
            records = [
                record
                for record in records
                if self._matches_query(record, request.query)
            ]

        limit = self.default_limit if request.limit is None else max(0, request.limit)
        selected_records = records[:limit]
        context_blocks = list(self.renderer.render(selected_records))
        return MemoryRetrievalResult(
            memory_context=context_blocks,
            records=selected_records,
            metadata={
                "retriever": "in_memory",
                "record_count": len(selected_records),
                "total_candidates": len(records),
            },
        )

    def _records_from_active_context(
        self,
        active_context: ActiveMemoryContext | None,
    ) -> list[MemoryRecord]:
        if not active_context:
            return []
        return [
            *active_context.event_memories,
            *active_context.entity_memories,
            *active_context.property_memories,
            *active_context.other_memories,
        ]

    def _dedupe(self, records: Sequence[MemoryRecord]) -> list[MemoryRecord]:
        deduped: list[MemoryRecord] = []
        seen: set[str] = set()
        for record in records:
            key = record.id or f"{record.memory_type}:{record.text}"
            if key in seen:
                continue
            seen.add(key)
            deduped.append(record)
        return deduped

    def _matches_query(self, record: MemoryRecord, query: str) -> bool:
        normalized_query = query.casefold().strip()
        if not normalized_query:
            return True
        searchable_parts = [
            record.text,
            str(record.metadata.get("name", "")),
            str(record.metadata.get("identity_summary", "")),
        ]
        searchable = " ".join(searchable_parts).casefold()
        return normalized_query in searchable
