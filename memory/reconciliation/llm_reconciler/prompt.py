"""Prompt construction for LLM-backed reconciliation."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from llm.interfaces import ChatMessageParam

from ...models import MemoryRecord
from ...retrieval import CandidateRelatedGroup, RelatedMemory
from ..models import MemoryReconciliationRequest
from .models import LLMReconciliationInput
from .references import candidate_id

_ACTIONS = {
    "create",
    "reuse",
    "attach",
    "update",
    "merge",
    "invalidate",
    "flag_conflict",
    "ignore",
}


class LLMReconciliationPromptBuilder:
    """Build a compact decision prompt for LLM reconciliation."""

    def build(self, request: MemoryReconciliationRequest) -> list[ChatMessageParam]:
        payload = self.build_input(request).to_record()
        return [
            {
                "role": "system",
                "content": (
                    "You are the memory reconciliation component. Decide how each "
                    "candidate memory should be written. Return JSON only. Do not "
                    "invent candidate ids or existing record ids. Every candidate "
                    "must have exactly one decision."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            },
        ]

    def build_repair(
        self,
        request: MemoryReconciliationRequest,
        previous_output: str,
        errors: Sequence[str],
    ) -> list[ChatMessageParam]:
        messages = self.build(request)
        messages.append({"role": "assistant", "content": previous_output})
        messages.append(
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "repair_errors": list(errors),
                        "instruction": (
                            "Repair the JSON response. Keep one valid decision per "
                            "candidate and use only ids present in the input."
                        ),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            }
        )
        return messages

    def build_input(self, request: MemoryReconciliationRequest) -> LLMReconciliationInput:
        return LLMReconciliationInput(
            candidates=[_candidate_payload(candidate) for candidate in request.candidates],
            candidate_graph=_candidate_graph(request.candidates),
            retrieval_groups=[_group_payload(group) for group in request.retrieval.groups],
            active_memory_context=(
                request.active_memory_context.to_record()
                if hasattr(request.active_memory_context, "to_record")
                else request.active_memory_context
            ),
            scope={
                "user_id": request.user_id,
                "session_id": request.session_id,
                "metadata": dict(request.metadata),
            },
            write_policy={
                "actions": sorted(_ACTIONS),
                "reusable_types": ["entity", "event", "property", "time_ref"],
                "dependent_types": ["description", "link", "time_link"],
                "attach_rules": {
                    "property": "target must be an entity record or entity candidate",
                    "description": "target must be an event record or event candidate",
                    "link": "all endpoint candidate ids must resolve",
                    "time_link": "target and time_ref must resolve",
                },
                "conflict_policy": (
                    "Use update when a new candidate clearly replaces one existing "
                    "record. Use invalidate when old records should stop being active. "
                    "Use flag_conflict when evidence is insufficient."
                ),
            },
            output_contract={
                "shape": {
                    "decisions": [
                        {
                            "candidate_id": "candidate client id",
                            "action": "create|reuse|attach|update|merge|invalidate|flag_conflict|ignore",
                            "existing_record_id": "required for reuse/update when using stored memory",
                            "target_record_id": "required for attach to stored memory",
                            "target_candidate_id": "required for attach/reuse to same-turn candidate",
                            "relation_type": "required for attach relation semantics",
                            "replacement_text": "optional update text",
                            "replacement_metadata": "optional update metadata",
                            "merge_source_record_ids": "records to mark merged",
                            "invalidated_record_ids": "records to mark invalidated",
                            "confidence": "low|medium|high",
                            "reason": "short justification",
                        }
                    ],
                    "summary": "optional short summary",
                    "warnings": [],
                }
            },
        )


def _candidate_payload(record: MemoryRecord) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id(record),
        "memory_type": record.memory_type,
        "text": record.text,
        "metadata": dict(record.metadata),
        "source_refs": [source.to_record() for source in record.source_refs],
    }


def _candidate_graph(candidates: Sequence[MemoryRecord]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        current_candidate_id = candidate_id(candidate)
        if not current_candidate_id:
            continue
        nodes[current_candidate_id] = {
            "memory_type": candidate.memory_type,
            "parent_candidate_ids": _parent_candidate_ids(candidate),
            "endpoint_candidate_ids": _endpoint_candidate_ids(candidate),
        }
    return {"nodes": nodes}


def _group_payload(group: CandidateRelatedGroup) -> dict[str, Any]:
    return {
        "candidate_id": group.candidate_id,
        "candidate_type": group.candidate_type,
        "candidate_text": group.candidate_text,
        "direct_matches": [_related_payload(item) for item in group.direct_matches],
        "expanded_context": [_related_payload(item) for item in group.expanded_context],
    }


def _related_payload(related: RelatedMemory) -> dict[str, Any]:
    return {
        "record": related.record.to_record(),
        "score": related.score,
        "reasons": list(related.reasons),
        "matched_candidate_id": related.matched_candidate_id,
        "match_kind": related.match_kind,
        "expansion_depth": related.expansion_depth,
    }


def _parent_candidate_ids(record: MemoryRecord) -> list[str]:
    keys = ("entity_client_id", "event_client_id")
    return [
        value for value in (record.metadata.get(key) for key in keys)
        if isinstance(value, str)
    ]


def _endpoint_candidate_ids(record: MemoryRecord) -> list[str]:
    keys = ("from_client_id", "to_client_id", "target_client_id", "time_ref_client_id")
    return [
        value for value in (record.metadata.get(key) for key in keys)
        if isinstance(value, str)
    ]
