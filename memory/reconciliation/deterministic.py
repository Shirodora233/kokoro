"""Legacy deterministic baseline memory reconciler.

This module is the rule-based fallback for the LLM reconciler. It is kept for
tests, local/offline operation, and safe fallback behavior, but it is no longer
the target reconciliation implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..models import MemoryRecord
from ..retrieval import CandidateRelatedGroup, RelatedMemory
from .models import (
    MemoryReconciliationRequest,
    MemoryWriteOperation,
    MemoryWritePlan,
    ReconciliationEvidence,
)

REUSABLE_TYPES = {"entity", "event", "property", "time_ref"}
DEPENDENT_TYPES = {"description", "link", "time_link"}


@dataclass
class _ResolvedCandidate:
    candidate: MemoryRecord
    existing_record_id: str | None = None
    action: str | None = None


class LegacyDeterministicMemoryReconciler:
    """Legacy rule-based reconciler used as an LLM fallback."""

    def reconcile(self, request: MemoryReconciliationRequest) -> MemoryWritePlan:
        candidate_by_id = self._candidate_index(request.candidates)
        resolved: dict[str, _ResolvedCandidate] = {
            candidate_id: _ResolvedCandidate(candidate)
            for candidate_id, candidate in candidate_by_id.items()
        }
        operations: list[MemoryWriteOperation] = []

        for group in request.retrieval.groups:
            candidate = candidate_by_id.get(group.candidate_id or "")
            if not candidate:
                continue
            if not self._same_type_direct_matches(group):
                continue
            operation = self._operation_for_group(group, candidate)
            operations.append(operation)
            self._mark_resolved(resolved, operation)

        grouped_ids = {
            group.candidate_id
            for group in request.retrieval.groups
            if group.candidate_id is not None
        }
        for candidate_id, candidate in candidate_by_id.items():
            if candidate_id in grouped_ids:
                continue
            operation = self._create_operation(candidate, reason="no retrieval group")
            operations.append(operation)
            self._mark_resolved(resolved, operation)

        for candidate_id, state in resolved.items():
            if state.action is not None:
                continue
            operation = self._operation_without_match(state.candidate, resolved)
            operations.append(operation)
            self._mark_resolved(resolved, operation)

        return MemoryWritePlan(
            operations=operations,
            metadata={
                "reconciler": "deterministic",
                "candidate_count": len(request.candidates),
                "operation_count": len(operations),
            },
        )

    def _operation_for_group(
        self,
        group: CandidateRelatedGroup,
        candidate: MemoryRecord,
    ) -> MemoryWriteOperation:
        direct_match = self._best_direct_match(group)
        if direct_match and candidate.memory_type in REUSABLE_TYPES:
            return self._reuse_operation(
                candidate=candidate,
                related=direct_match,
                reason=f"direct {candidate.memory_type} match",
            )
        if direct_match and candidate.memory_type in DEPENDENT_TYPES:
            return self._ignore_operation(
                candidate=candidate,
                related=direct_match,
                reason=f"dependent {candidate.memory_type} already exists",
            )
        return self._create_operation(candidate, reason="no direct reusable match")

    def _operation_without_match(
        self,
        candidate: MemoryRecord,
        resolved: dict[str, _ResolvedCandidate],
    ) -> MemoryWriteOperation:
        if candidate.memory_type == "property":
            target_id, target_candidate_id = self._resolved_parent_target(
                resolved,
                candidate.metadata.get("entity_client_id"),
            )
            if target_id or target_candidate_id:
                return self._attach_operation(
                    candidate=candidate,
                    target_record_id=target_id,
                    target_candidate_id=target_candidate_id,
                    relation_type="has_property",
                    reason="property attaches to resolved entity",
                )
        if candidate.memory_type == "description":
            target_id, target_candidate_id = self._resolved_parent_target(
                resolved,
                candidate.metadata.get("event_client_id"),
            )
            if target_id or target_candidate_id:
                return self._attach_operation(
                    candidate=candidate,
                    target_record_id=target_id,
                    target_candidate_id=target_candidate_id,
                    relation_type="has_description",
                    reason="description attaches to resolved event",
                )
        if candidate.memory_type in {"link", "time_link"}:
            endpoint_ids = self._resolved_endpoint_ids(candidate, resolved)
            if endpoint_ids:
                return self._attach_operation(
                    candidate=candidate,
                    target_record_id=None,
                    relation_type=self._relation_type(candidate),
                    reason="relation endpoints resolved",
                    metadata={"resolved_endpoint_ids": endpoint_ids},
                )
        return self._create_operation(candidate, reason="no resolved parent")

    def _reuse_operation(
        self,
        candidate: MemoryRecord,
        related: RelatedMemory,
        reason: str,
    ) -> MemoryWriteOperation:
        return MemoryWriteOperation(
            action="reuse",
            candidate_id=self._candidate_id(candidate),
            candidate_type=candidate.memory_type,
            candidate_text=candidate.text,
            record=candidate,
            existing_record_id=related.record.id,
            reason=reason,
            confidence=self._confidence(related.score),
            evidence=[self._evidence(related)],
        )

    def _create_operation(
        self,
        candidate: MemoryRecord,
        reason: str,
    ) -> MemoryWriteOperation:
        return MemoryWriteOperation(
            action="create",
            candidate_id=self._candidate_id(candidate),
            candidate_type=candidate.memory_type,
            candidate_text=candidate.text,
            record=candidate,
            reason=reason,
            confidence="medium",
        )

    def _attach_operation(
        self,
        candidate: MemoryRecord,
        target_record_id: str | None,
        relation_type: str | None,
        reason: str,
        target_candidate_id: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> MemoryWriteOperation:
        return MemoryWriteOperation(
            action="attach",
            candidate_id=self._candidate_id(candidate),
            candidate_type=candidate.memory_type,
            candidate_text=candidate.text,
            record=candidate,
            target_record_id=target_record_id,
            target_candidate_id=target_candidate_id,
            relation_type=relation_type,
            reason=reason,
            confidence="medium",
            metadata=dict(metadata or {}),
        )

    def _ignore_operation(
        self,
        candidate: MemoryRecord,
        related: RelatedMemory,
        reason: str,
    ) -> MemoryWriteOperation:
        return MemoryWriteOperation(
            action="ignore",
            candidate_id=self._candidate_id(candidate),
            candidate_type=candidate.memory_type,
            candidate_text=candidate.text,
            record=candidate,
            existing_record_id=related.record.id,
            reason=reason,
            confidence=self._confidence(related.score),
            evidence=[self._evidence(related)],
        )

    def _best_direct_match(
        self,
        group: CandidateRelatedGroup,
    ) -> RelatedMemory | None:
        matches = self._same_type_direct_matches(group)
        if not matches:
            return None
        return max(matches, key=lambda related: related.score)

    def _same_type_direct_matches(
        self,
        group: CandidateRelatedGroup,
    ) -> list[RelatedMemory]:
        return [
            related for related in group.direct_matches
            if related.record.memory_type == group.candidate_type
        ]

    def _mark_resolved(
        self,
        resolved: dict[str, _ResolvedCandidate],
        operation: MemoryWriteOperation,
    ) -> None:
        if operation.candidate_id is None:
            return
        state = resolved.get(operation.candidate_id)
        if not state:
            return
        state.action = operation.action
        if operation.action == "reuse":
            state.existing_record_id = operation.existing_record_id

    def _resolved_parent_id(
        self,
        resolved: dict[str, _ResolvedCandidate],
        parent_candidate_id: object,
    ) -> str | None:
        existing_record_id, _ = self._resolved_parent_target(
            resolved,
            parent_candidate_id,
        )
        return existing_record_id

    def _resolved_parent_target(
        self,
        resolved: dict[str, _ResolvedCandidate],
        parent_candidate_id: object,
    ) -> tuple[str | None, str | None]:
        if not isinstance(parent_candidate_id, str):
            return None, None
        parent = resolved.get(parent_candidate_id)
        if not parent or parent.action is None:
            return None, None
        return parent.existing_record_id, parent_candidate_id

    def _resolved_endpoint_ids(
        self,
        candidate: MemoryRecord,
        resolved: dict[str, _ResolvedCandidate],
    ) -> list[str]:
        ids: list[str] = []
        for candidate_id in self._endpoint_candidate_ids(candidate):
            endpoint_id = self._resolved_parent_id(resolved, candidate_id)
            if endpoint_id:
                ids.append(endpoint_id)
        return ids

    def _endpoint_candidate_ids(self, candidate: MemoryRecord) -> list[str]:
        keys = [
            "from_client_id",
            "to_client_id",
            "target_client_id",
            "time_ref_client_id",
        ]
        return [
            value for value in (
                candidate.metadata.get(key) for key in keys
            )
            if isinstance(value, str)
        ]

    def _relation_type(self, candidate: MemoryRecord) -> str | None:
        relation = candidate.metadata.get("relation_type")
        if isinstance(relation, str):
            return relation
        time_role = candidate.metadata.get("time_role")
        if isinstance(time_role, str):
            return time_role
        return None

    def _candidate_index(
        self,
        candidates: Sequence[MemoryRecord],
    ) -> dict[str, MemoryRecord]:
        index: dict[str, MemoryRecord] = {}
        for position, candidate in enumerate(candidates):
            candidate_id = self._candidate_id(candidate) or f"candidate_{position}"
            index[candidate_id] = candidate
        return index

    def _candidate_id(self, candidate: MemoryRecord) -> str | None:
        value = candidate.metadata.get("candidate_client_id")
        if isinstance(value, str) and value:
            return value
        return candidate.id

    def _evidence(self, related: RelatedMemory) -> ReconciliationEvidence:
        return ReconciliationEvidence(
            source="candidate_retrieval",
            record_id=related.record.id,
            candidate_id=related.matched_candidate_id,
            score=related.score,
            reasons=related.reasons,
            metadata={
                "match_kind": related.match_kind,
                "expansion_depth": related.expansion_depth,
            },
        )

    def _confidence(self, score: float) -> str:
        if score >= 3.0:
            return "high"
        if score >= 1.5:
            return "medium"
        return "low"


DeterministicMemoryReconciler = LegacyDeterministicMemoryReconciler
