"""Interfaces for memory reconciliation."""

from __future__ import annotations

from typing import Protocol

from .models import MemoryReconciliationRequest, MemoryWritePlan


class MemoryReconciler(Protocol):
    """Turn extracted candidates and related memories into a write plan."""

    def reconcile(self, request: MemoryReconciliationRequest) -> MemoryWritePlan:
        """Return planned write operations without mutating storage."""
