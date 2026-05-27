"""No-op memory system implementation for wiring and tests."""

from __future__ import annotations

from .interfaces import MemorySystem
from .models import (
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySearchResult,
    MemoryTurnCommitInput,
    MemoryTurnInput,
    MemoryTurnPrepareResult,
    MemoryTurnResult,
    MemoryTurnSnapshot,
)


class NoopMemorySystem(MemorySystem):
    """Memory boundary implementation that preserves existing behavior."""

    def prepare_turn(self, turn: MemoryTurnInput) -> MemoryTurnPrepareResult:
        snapshot = MemoryTurnSnapshot(
            turn=turn,
            search_result=MemorySearchResult(metadata={"search": "noop"}),
            metadata={"memory_runtime": self.__class__.__name__},
        )
        return MemoryTurnPrepareResult(snapshot=snapshot, metadata=snapshot.metadata)

    def commit_turn(self, commit: MemoryTurnCommitInput) -> MemoryTurnResult:
        return MemoryTurnResult()

    def retrieve_context(self, request: MemoryRetrievalRequest) -> MemoryRetrievalResult:
        return MemoryRetrievalResult()
