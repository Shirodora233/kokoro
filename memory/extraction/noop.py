"""Extractor placeholder used before LLM-backed extraction exists."""

from __future__ import annotations

from typing import Sequence

from ..models import MemoryRecord, MemoryTurnInput


class NoopMemoryExtractor:
    """Return no candidates while keeping the extraction boundary real."""

    def extract(self, turn: MemoryTurnInput) -> Sequence[MemoryRecord]:
        return []
