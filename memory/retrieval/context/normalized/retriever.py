"""Normalized memory context retrieval orchestration."""

from __future__ import annotations

from ....models import (
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySearchRequest,
    MemorySearchResult,
)
from ....persistence import PersistentMemoryRepository
from .hydrator import NormalizedMemoryHydrator
from .renderer import NormalizedMemoryContextRenderer
from .search import FallbackNormalizedMemorySearch, NormalizedMemorySearch


class NormalizedMemoryContextRetriever:
    """Retrieve prompt-ready memory context from normalized persistence tables.

    Low-level relation objects such as raw links and time-links are used during
    hydration, but only event/entity views are rendered into prompt context.
    """

    def __init__(
        self,
        repository: PersistentMemoryRepository,
        search: NormalizedMemorySearch | None = None,
        renderer: NormalizedMemoryContextRenderer | None = None,
        hydrator: NormalizedMemoryHydrator | None = None,
        default_limit: int = 8,
        pool_limit: int = 40,
    ) -> None:
        self.repository = repository
        self.searcher = search or FallbackNormalizedMemorySearch(
            repository,
            pool_limit=pool_limit,
        )
        self.renderer = renderer or NormalizedMemoryContextRenderer()
        self.hydrator = hydrator or NormalizedMemoryHydrator(
            repository,
            default_limit=default_limit,
            pool_limit=pool_limit,
        )
        self.default_limit = default_limit
        self.pool_limit = pool_limit

    def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        return self.searcher.search(request)

    def retrieve_from_search(
        self,
        search_result: MemorySearchResult,
        request: MemoryRetrievalRequest,
    ) -> MemoryRetrievalResult:
        limit = self.default_limit if request.limit is None else max(0, request.limit)
        if limit == 0:
            return MemoryRetrievalResult(
                metadata={"retriever": "normalized", "record_count": 0}
            )

        hydrated = self.hydrator.load_views(request, search_result.hits)
        selected = self.renderer.select_views(
            event_views=hydrated.event_views,
            entity_views=hydrated.entity_views,
            selected_view_refs=hydrated.selected_view_refs,
            limit=limit,
        )
        context_blocks = self.renderer.render_context(selected)
        return MemoryRetrievalResult(
            memory_context=context_blocks,
            records=[view.record for view in selected],
            metadata={
                "retriever": "normalized",
                "repository": self.repository.__class__.__name__,
                "search": search_result.metadata,
                "record_count": len(selected),
                "event_view_count": len(hydrated.event_views),
                "entity_view_count": len(hydrated.entity_views),
                "selected_view_refs": [
                    {"kind": kind, "id": object_id}
                    for kind, object_id in hydrated.selected_view_refs
                ],
                "selected_view_keys": [view.key for view in selected],
                "selected_view_kinds": [view.kind for view in selected],
                "context_block_count": len(context_blocks),
                "query": request.query,
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
                limit=max(limit * 4, limit),
                metadata=dict(request.metadata),
            )
        )
        return self.retrieve_from_search(search_result, request)
