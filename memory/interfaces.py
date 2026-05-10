"""Interfaces for memory processing components."""

from __future__ import annotations

from typing import Protocol, Sequence

from .models import (
    ContextAction,
    MemoryContextBlock,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemoryTurnInput,
    MemoryTurnResult,
)


class MemorySystem(Protocol):
    """High-level memory boundary used by conversation and other producers."""

    def process_turn(self, turn: MemoryTurnInput) -> MemoryTurnResult:
        """Process one new message with conversation context."""

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


class MemoryRetriever(Protocol):
    """Retrieve memory records and prompt context."""

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
