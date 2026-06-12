"""Compile LLM decisions into memory write plans."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ...models import MemoryRecord
from ..models import (
    MemoryReconciliationRequest,
    MemoryWriteOperation,
    MemoryWritePlan,
    ReconciliationEvidence,
)
from .models import LLMReconciliationDecision, LLMReconciliationResponse
from .references import candidate_id, relation_type


class MemoryWritePlanCompiler:
    """Compile validated LLM decisions into a provider-neutral write plan."""

    def compile(
        self,
        response: LLMReconciliationResponse,
        request: MemoryReconciliationRequest,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryWritePlan:
        candidates = {
            candidate_id(candidate): candidate
            for candidate in request.candidates
            if candidate_id(candidate)
        }
        operations = [
            self._operation(decision, candidates[decision.candidate_id], request)
            for decision in response.decisions
            if decision.candidate_id in candidates
        ]
        return MemoryWritePlan(
            operations=operations,
            metadata={
                **dict(metadata or {}),
                "reconciler": "llm",
                "candidate_count": len(request.candidates),
                "operation_count": len(operations),
                "summary": response.summary,
                "warnings": [*response.warnings, *(metadata or {}).get("warnings", [])],
            },
        )

    def _operation(
        self,
        decision: LLMReconciliationDecision,
        candidate: MemoryRecord,
        request: MemoryReconciliationRequest,
    ) -> MemoryWriteOperation:
        replacement = self._replacement(decision, candidate)
        return MemoryWriteOperation(
            action=decision.action,
            candidate_id=decision.candidate_id,
            candidate_type=candidate.memory_type,
            candidate_text=candidate.text,
            record=replacement,
            existing_record_id=decision.existing_record_id,
            target_record_id=decision.target_record_id,
            target_candidate_id=decision.target_candidate_id,
            relation_type=decision.relation_type or relation_type(candidate),
            replacement=replacement if decision.action == "update" else None,
            merge_source_record_ids=list(decision.merge_source_record_ids),
            invalidated_record_ids=list(decision.invalidated_record_ids),
            reason=decision.reason,
            confidence=decision.confidence,
            evidence=[
                self._evidence(item, decision, request)
                for item in decision.evidence
            ],
            metadata={
                **dict(decision.metadata),
                "llm_action": decision.action,
            },
        )

    def _replacement(
        self,
        decision: LLMReconciliationDecision,
        candidate: MemoryRecord,
    ) -> MemoryRecord:
        metadata = dict(candidate.metadata)
        metadata.update(decision.replacement_metadata)
        text = decision.replacement_text or candidate.text
        return replace(candidate, text=text, metadata=metadata)

    def _evidence(
        self,
        item: dict[str, Any],
        decision: LLMReconciliationDecision,
        request: MemoryReconciliationRequest,
    ) -> ReconciliationEvidence:
        record_id = _string(item.get("record_id")) or decision.existing_record_id
        return ReconciliationEvidence(
            source=_string(item.get("source")) or "llm_reconciliation",
            record_id=record_id,
            candidate_id=decision.candidate_id,
            score=_float(item.get("score")),
            reasons=_string_list(item.get("reasons")) or [decision.reason],
            metadata={
                "request_source": request.metadata.get("source"),
                **_dict(item.get("metadata")),
            },
        )


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _float(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None
