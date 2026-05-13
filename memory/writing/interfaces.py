"""Interfaces for applying memory write plans."""

from __future__ import annotations

from typing import Protocol

from .models import MemoryWriteRequest, MemoryWriteResult


class MemoryWritePlanApplier(Protocol):
    """Apply a reconciled write plan to a concrete store."""

    def apply(self, request: MemoryWriteRequest) -> MemoryWriteResult:
        """Apply a plan and return created/reused/failed records."""
