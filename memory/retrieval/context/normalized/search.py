"""Search boundary for normalized memory context retrieval."""

from __future__ import annotations

from typing import Protocol

from ....models import MemorySearchRequest, MemorySearchResult


class NormalizedMemorySearch(Protocol):
    def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        """Return normalized object refs that should be hydrated for prompting."""
