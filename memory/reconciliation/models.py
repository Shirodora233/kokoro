"""DTOs for memory reconciliation and write planning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Sequence

from ..models import MemoryRecord
from ..retrieval import CandidateRetrievalResult

WriteAction = Literal[
    "create",
    "reuse",
    "attach",
    "flag_conflict",
    "ignore",
]
ReconciliationConfidence = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ReconciliationEvidence:
    """Evidence used by a reconciler to justify one write operation."""

    source: str
    record_id: str | None = None
    candidate_id: str | None = None
    score: float | None = None
    reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryWriteOperation:
    """One planned memory write/reuse/attach decision.

    This is intentionally provider-neutral so deterministic and LLM-backed
    reconcilers can emit the same contract.
    """

    action: WriteAction
    candidate_id: str | None
    candidate_type: str
    candidate_text: str
    record: MemoryRecord | None = None
    existing_record_id: str | None = None
    target_record_id: str | None = None
    target_candidate_id: str | None = None
    relation_type: str | None = None
    reason: str = ""
    confidence: ReconciliationConfidence = "medium"
    evidence: list[ReconciliationEvidence] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryWritePlan:
    """Planned reconciliation result. It does not mutate storage."""

    operations: list[MemoryWriteOperation] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryReconciliationRequest:
    """Input to a memory reconciler."""

    candidates: Sequence[MemoryRecord]
    retrieval: CandidateRetrievalResult
    user_id: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "candidates": [
                candidate.to_record() for candidate in self.candidates
            ],
            "retrieval": self.retrieval.to_record(),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "metadata": self.metadata,
        }
