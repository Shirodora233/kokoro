"""DTOs for applying memory write plans."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from ..models import MemoryRecord
from ..reconciliation import MemoryWriteOperation, MemoryWritePlan


@dataclass(frozen=True)
class MemoryWriteRequest:
    """Request to apply a reconciled write plan to storage."""

    plan: MemoryWritePlan
    user_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "plan": self.plan.to_record(),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class MemoryWriteFailure:
    """One write operation that could not be applied."""

    operation: MemoryWriteOperation
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryWriteResult:
    """Result of applying a memory write plan."""

    created_records: list[MemoryRecord] = field(default_factory=list)
    reused_records: list[MemoryRecord] = field(default_factory=list)
    attached_records: list[MemoryRecord] = field(default_factory=list)
    ignored_operations: list[MemoryWriteOperation] = field(default_factory=list)
    conflict_operations: list[MemoryWriteOperation] = field(default_factory=list)
    failed_operations: list[MemoryWriteFailure] = field(default_factory=list)
    candidate_record_ids: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
