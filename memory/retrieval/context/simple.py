"""Simple store-backed memory context retrieval and rendering."""

from __future__ import annotations

from typing import Sequence

from ...interfaces import MemoryContextRenderer, MemoryStore
from ...models import (
    ActiveMemoryContext,
    MemoryContextBlock,
    MemoryObjectRef,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySearchHit,
    MemorySearchRequest,
    MemorySearchResult,
)


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


class SimpleMemoryContextRetriever:
    """Scope-aware context retrieval over a generic memory store."""

    def __init__(
        self,
        store: MemoryStore,
        renderer: MemoryContextRenderer | None = None,
        default_limit: int = 8,
    ) -> None:
        self.store = store
        self.renderer = renderer or SimpleMemoryContextRenderer()
        self.default_limit = default_limit

    def search(self, request: MemorySearchRequest) -> MemorySearchResult:
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

        limit = max(0, request.limit)
        hits = [
            MemorySearchHit(
                object_ref=MemoryObjectRef(record.memory_type, record.id or ""),
                score=1.0,
                reason="store_text_match",
                matched_text=record.text,
                record=record,
                metadata={"source": "simple_store_context"},
            )
            for record in records[:limit]
            if record.id
        ]
        return MemorySearchResult(
            hits=hits,
            metadata={
                "search": "simple_store_context",
                "store": self.store.__class__.__name__,
                "hit_count": len(hits),
                "total_candidates": len(records),
            },
        )

    def retrieve_from_search(
        self,
        search_result: MemorySearchResult,
        request: MemoryRetrievalRequest,
    ) -> MemoryRetrievalResult:
        limit = self.default_limit if request.limit is None else max(0, request.limit)
        selected_records = [
            hit.record
            for hit in search_result.hits
            if hit.record is not None
        ][:limit]
        context_blocks = list(self.renderer.render(selected_records))
        return MemoryRetrievalResult(
            memory_context=context_blocks,
            records=selected_records,
            metadata={
                "retriever": "simple_store_context",
                "store": self.store.__class__.__name__,
                "record_count": len(selected_records),
                "search": search_result.metadata,
            },
        )

    def retrieve(self, request: MemoryRetrievalRequest) -> MemoryRetrievalResult:
        limit = self.default_limit if request.limit is None else max(0, request.limit)
        search_result = self.search(
            MemorySearchRequest(
                user_id=request.user_id,
                session_id=request.session_id,
                query=request.query,
                timezone=request.timezone,
                active_memory_context=request.active_memory_context,
                limit=limit,
                metadata=dict(request.metadata),
            )
        )
        return self.retrieve_from_search(search_result, request)

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
        searchable = " ".join(searchable_parts).casefold().strip()
        if not searchable:
            return False
        return normalized_query in searchable or searchable in normalized_query
