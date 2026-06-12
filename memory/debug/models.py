"""Structured debug DTOs for memory extraction and retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from llm.interfaces import ChatMessageParam

from ..models import (
    ActiveMemoryContext,
    MemoryContextBlock,
    MemoryInputMessage,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySearchRequest,
    MemorySearchResult,
)

DEBUG_TRACE_ID_KEY = "debug_trace_id"


def new_debug_trace_id() -> str:
    return f"memdbg_{uuid4().hex}"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ExtractionDebugInfo:
    """Debug details for one extraction call."""

    input_summary: dict[str, Any] = field(default_factory=dict)
    prompt_messages: list[ChatMessageParam] = field(default_factory=list)
    raw_output: str | None = None
    raw_prompt_truncated: bool = False
    raw_output_truncated: bool = False
    parse_status: str = "not_run"
    parse_error: str | None = None
    parsed_candidate_counts: dict[str, int] = field(default_factory=dict)
    validated_candidate_counts: dict[str, int] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)
    normalized_records: list[MemoryRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self, include_raw: bool = False) -> dict[str, Any]:
        payload = {
            "input_summary": dict(self.input_summary),
            "parse_status": self.parse_status,
            "parse_error": self.parse_error,
            "parsed_candidate_counts": dict(self.parsed_candidate_counts),
            "validated_candidate_counts": dict(self.validated_candidate_counts),
            "dropped_candidate_counts": _count_delta(
                self.parsed_candidate_counts,
                self.validated_candidate_counts,
            ),
            "validation_errors": list(self.validation_errors),
            "normalized_records": [
                record.to_record() for record in self.normalized_records
            ],
            "raw": {
                "available": bool(self.prompt_messages or self.raw_output),
                "prompt_message_count": len(self.prompt_messages),
                "raw_output_length": len(self.raw_output or ""),
                "prompt_truncated": self.raw_prompt_truncated,
                "output_truncated": self.raw_output_truncated,
            },
            "metadata": dict(self.metadata),
        }
        if include_raw:
            payload["prompt_messages"] = [dict(message) for message in self.prompt_messages]
            payload["raw_output"] = self.raw_output
        return payload


@dataclass(frozen=True)
class RetrievalDebugInfo:
    """Debug details for memory search and prompt context rendering."""

    active_memory_context: ActiveMemoryContext | None = None
    scoped_candidates: list[MemoryRecord] = field(default_factory=list)
    search_request: MemorySearchRequest | None = None
    search_result: MemorySearchResult | None = None
    retrieval_request: MemoryRetrievalRequest | None = None
    retrieval_result: MemoryRetrievalResult | None = None
    memory_context: list[MemoryContextBlock] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "active_memory_context": (
                self.active_memory_context.to_record()
                if self.active_memory_context is not None
                else None
            ),
            "scoped_candidates": [
                record.to_record() for record in self.scoped_candidates
            ],
            "search_request": (
                self.search_request.to_record()
                if self.search_request is not None
                else None
            ),
            "search_result": (
                self.search_result.to_record()
                if self.search_result is not None
                else None
            ),
            "retrieval_request": (
                self.retrieval_request.to_record()
                if self.retrieval_request is not None
                else None
            ),
            "retrieval_result": (
                self.retrieval_result.to_record()
                if self.retrieval_result is not None
                else None
            ),
            "memory_context": [block.to_record() for block in self.memory_context],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class WriteDebugInfo:
    """Debug details for memory reconciliation and write application."""

    candidate_matching: Any | None = None
    write_plan: Any | None = None
    write_result: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "candidate_matching": _to_record(self.candidate_matching),
            "write_plan": _sanitize_write_plan(_to_record(self.write_plan)),
            "write_result": _to_record(self.write_result),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class MemoryDebugTrace:
    """One user-message memory debug trace."""

    trace_id: str
    user_id: str | None
    session_id: str | None
    message_id: str | None
    created_at: str = field(default_factory=utc_now_iso)
    status: str = "started"
    new_message: MemoryInputMessage | None = None
    extraction: ExtractionDebugInfo | None = None
    retrieval: RetrievalDebugInfo | None = None
    write: WriteDebugInfo | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self, include_raw: bool = False) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "created_at": self.created_at,
            "status": self.status,
            "new_message": (
                self.new_message.to_record()
                if self.new_message is not None
                else None
            ),
            "extraction": (
                self.extraction.to_record(include_raw=include_raw)
                if self.extraction is not None
                else None
            ),
            "retrieval": (
                self.retrieval.to_record()
                if self.retrieval is not None
                else None
            ),
            "write": (
                self.write.to_record()
                if self.write is not None
                else None
            ),
            "metadata": dict(self.metadata),
        }

    def to_summary_record(self) -> dict[str, Any]:
        extraction = self.extraction
        retrieval = self.retrieval
        search_result = retrieval.search_result if retrieval else None
        write_record = self.write.to_record() if self.write else {}
        write_plan = (
            write_record.get("write_plan") if isinstance(write_record, dict) else {}
        )
        write_plan = write_plan if isinstance(write_plan, dict) else {}
        write_metadata = write_plan.get("metadata")
        write_metadata = write_metadata if isinstance(write_metadata, dict) else {}
        write_operations = write_plan.get("operations")
        write_operations = write_operations if isinstance(write_operations, list) else []
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "message_id": self.message_id,
            "created_at": self.created_at,
            "status": self.status,
            "parse_status": extraction.parse_status if extraction else None,
            "parse_error": extraction.parse_error if extraction else None,
            "candidate_count": (
                len(extraction.normalized_records) if extraction else 0
            ),
            "search_hit_count": len(search_result.hits) if search_result else 0,
            "memory_context_count": (
                len(retrieval.memory_context) if retrieval else 0
            ),
            "reconciler": write_metadata.get("reconciler"),
            "write_operation_count": len(write_operations),
            "write_action_counts": _write_action_counts(write_operations),
            "metadata": dict(self.metadata),
        }


def trace_id_from_metadata(metadata: dict[str, Any] | None) -> str | None:
    if not metadata:
        return None
    value = metadata.get(DEBUG_TRACE_ID_KEY)
    return value if isinstance(value, str) and value else None


def _count_delta(
    before: dict[str, int],
    after: dict[str, int],
) -> dict[str, int]:
    keys = set(before) | set(after)
    return {
        key: max(0, before.get(key, 0) - after.get(key, 0))
        for key in sorted(keys)
    }


def _to_record(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "to_record"):
        return value.to_record()
    return value


def _sanitize_write_plan(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    plan = dict(value)
    metadata = dict(plan.get("metadata") or {})
    raw_output = metadata.pop("raw_output", None)
    prompt_messages = metadata.pop("prompt_messages", None)
    llm_raw_outputs = metadata.pop("llm_raw_outputs", None)
    raw: dict[str, Any] = {}
    if raw_output is not None:
        raw["raw_output_length"] = len(str(raw_output))
    if isinstance(prompt_messages, list):
        raw["prompt_message_count"] = len(prompt_messages)
    if isinstance(llm_raw_outputs, list):
        raw["fallback_raw_output_count"] = len(llm_raw_outputs)
    if raw:
        metadata["raw"] = {"available": True, **raw}
    plan["metadata"] = metadata
    return plan


def _write_action_counts(operations: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for operation in operations:
        if not isinstance(operation, dict):
            continue
        action = operation.get("action")
        if isinstance(action, str) and action:
            counts[action] = counts.get(action, 0) + 1
    return counts
