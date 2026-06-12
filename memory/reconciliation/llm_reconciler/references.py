"""Shared reference helpers for LLM reconciliation."""

from __future__ import annotations

from collections.abc import Sequence

from ...models import MemoryRecord
from ...retrieval import CandidateRelatedGroup


def candidate_id(record: MemoryRecord) -> str | None:
    value = record.metadata.get("candidate_client_id")
    if isinstance(value, str) and value:
        return value
    return record.id


def related_record_ids(groups: Sequence[CandidateRelatedGroup]) -> set[str]:
    record_ids: set[str] = set()
    for group in groups:
        for related in [*group.direct_matches, *group.expanded_context]:
            if related.record.id:
                record_ids.add(related.record.id)
    return record_ids


def relation_type(candidate: MemoryRecord) -> str | None:
    relation = candidate.metadata.get("relation_type")
    if isinstance(relation, str):
        return relation
    time_role = candidate.metadata.get("time_role")
    if isinstance(time_role, str):
        return time_role
    if candidate.memory_type == "property":
        return "has_property"
    if candidate.memory_type == "description":
        return "has_description"
    return None
