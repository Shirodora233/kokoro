"""Interfaces for memory processing components."""

from __future__ import annotations

from typing import Protocol, Sequence

from .models import (
    ContextAction,
    MemoryContextBlock,
    MemoryRecord,
    MemoryRecordType,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryTurnCommitInput,
    MemoryTurnInput,
    MemoryTurnPrepareResult,
    MemoryTurnResult,
)


class MemorySystem(Protocol):
    """High-level memory boundary used by conversation and other producers."""

    def prepare_turn(self, turn: MemoryTurnInput) -> MemoryTurnPrepareResult:
        """Prepare memory context and a reusable turn snapshot before an LLM call."""

    def commit_turn(self, commit: MemoryTurnCommitInput) -> MemoryTurnResult:
        """Commit a prepared turn after an LLM response."""

    def retrieve_context(self, request: MemoryRetrievalRequest) -> MemoryRetrievalResult:
        """Return memory context without ingesting a new turn."""


class MemoryExtractor(Protocol):
    """Extract candidate memories from a contextual turn."""

    def extract(self, turn: MemoryTurnInput) -> Sequence[MemoryRecord]:
        """Return candidate memory records."""


class MemoryStore(Protocol):
    """Persistence boundary for memory records."""

    def save_records(self, records: Sequence[MemoryRecord]) -> Sequence[MemoryRecord]:
        """Persist memory records and return stored records."""

    def get_records(self, record_ids: Sequence[str]) -> Sequence[MemoryRecord]:
        """Load stored memory records by id."""

    def list_records(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        memory_type: MemoryRecordType | None = None,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        """Load memory records by scope and type."""


class MemoryContextRetriever(Protocol):
    """Search memory and render prompt context."""

    def search(self, request: MemorySearchRequest) -> MemorySearchResult:
        """Return the reusable memory search snapshot for a request."""

    def retrieve_from_search(
        self,
        search_result: MemorySearchResult,
        request: MemoryRetrievalRequest,
    ) -> MemoryRetrievalResult:
        """Render prompt context from a precomputed search result."""

    def retrieve(self, request: MemoryRetrievalRequest) -> MemoryRetrievalResult:
        """Return records and context blocks relevant to a request."""


class ContextPolicy(Protocol):
    """Decide conversation context maintenance actions."""

    def plan_actions(self, turn: MemoryTurnInput) -> Sequence[ContextAction]:
        """Return suggested context actions for conversation to execute."""


class MemoryContextRenderer(Protocol):
    """Render memory records into prompt-ready context blocks."""

    def render(self, records: Sequence[MemoryRecord]) -> Sequence[MemoryContextBlock]:
        """Convert records into context blocks."""
