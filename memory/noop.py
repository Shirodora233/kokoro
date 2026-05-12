"""No-op memory system implementation for wiring and tests."""

from __future__ import annotations

from .interfaces import MemorySystem
from .models import MemoryRetrievalRequest, MemoryRetrievalResult, MemoryTurnInput, MemoryTurnResult


class NoopMemorySystem(MemorySystem):
    """Memory boundary implementation that preserves existing behavior."""

    def process_turn(self, turn: MemoryTurnInput) -> MemoryTurnResult:
        return MemoryTurnResult()

    def retrieve_context(self, request: MemoryRetrievalRequest) -> MemoryRetrievalResult:
        return MemoryRetrievalResult()
