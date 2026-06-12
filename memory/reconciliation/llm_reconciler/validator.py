"""Validation for LLM reconciliation decisions."""

from __future__ import annotations

from .models import (
    LLMReconciliationDecision,
    LLMReconciliationResponse,
    LLMReconciliationValidationResult,
)
from .references import candidate_id, related_record_ids
from ..models import MemoryReconciliationRequest


class ReconciliationDecisionValidator:
    """Validate LLM decisions against the request graph and retrieved records."""

    def validate(
        self,
        response: LLMReconciliationResponse,
        request: MemoryReconciliationRequest,
    ) -> LLMReconciliationValidationResult:
        candidate_ids = {candidate_id(candidate) for candidate in request.candidates}
        candidate_ids.discard(None)
        record_ids = related_record_ids(request.retrieval.groups)
        errors: list[str] = []
        warnings: list[str] = []
        seen: set[str] = set()

        for decision in response.decisions:
            if decision.candidate_id not in candidate_ids:
                errors.append(f"unknown candidate_id: {decision.candidate_id}")
                continue
            if decision.candidate_id in seen:
                errors.append(f"duplicate decision for candidate_id: {decision.candidate_id}")
            seen.add(decision.candidate_id)
            self._validate_decision(decision, candidate_ids, record_ids, errors)

        missing = sorted(candidate_ids - seen)
        if missing:
            errors.append("missing decisions for candidate_ids: " + ", ".join(missing))
        return LLMReconciliationValidationResult(errors=errors, warnings=warnings)

    def _validate_decision(
        self,
        decision: LLMReconciliationDecision,
        candidate_ids: set[str | None],
        record_ids: set[str],
        errors: list[str],
    ) -> None:
        if decision.existing_record_id and decision.existing_record_id not in record_ids:
            errors.append(
                f"{decision.candidate_id} references unknown existing_record_id: "
                f"{decision.existing_record_id}"
            )
        if decision.target_record_id and decision.target_record_id not in record_ids:
            errors.append(
                f"{decision.candidate_id} references unknown target_record_id: "
                f"{decision.target_record_id}"
            )
        if decision.target_candidate_id and decision.target_candidate_id not in candidate_ids:
            errors.append(
                f"{decision.candidate_id} references unknown target_candidate_id: "
                f"{decision.target_candidate_id}"
            )
        for record_id in [
            *decision.merge_source_record_ids,
            *decision.invalidated_record_ids,
        ]:
            if record_id not in record_ids:
                errors.append(
                    f"{decision.candidate_id} references unknown record_id: {record_id}"
                )
        if decision.action in {"reuse", "update"} and not (
            decision.existing_record_id or decision.target_candidate_id
        ):
            errors.append(
                f"{decision.candidate_id} action {decision.action} needs existing_record_id "
                "or target_candidate_id"
            )
        if decision.action == "attach" and not (
            decision.target_record_id or decision.target_candidate_id
        ):
            errors.append(
                f"{decision.candidate_id} attach needs target_record_id or target_candidate_id"
            )
        if decision.action == "merge" and not decision.merge_source_record_ids:
            errors.append(f"{decision.candidate_id} merge needs merge_source_record_ids")
        if decision.action == "invalidate" and not decision.invalidated_record_ids:
            errors.append(f"{decision.candidate_id} invalidate needs invalidated_record_ids")
