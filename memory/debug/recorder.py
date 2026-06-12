"""In-memory debug trace recorder for memory runtime observation."""

from __future__ import annotations

from collections import deque
from dataclasses import replace
from threading import RLock
from typing import Any, Sequence

from llm.interfaces import ChatMessageParam

from ..models import (
    MemoryInputMessage,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySearchRequest,
    MemorySearchResult,
    MemoryTurnInput,
)
from .models import (
    DEBUG_TRACE_ID_KEY,
    ExtractionDebugInfo,
    MemoryDebugTrace,
    RetrievalDebugInfo,
    WriteDebugInfo,
    new_debug_trace_id,
    trace_id_from_metadata,
)


class MemoryDebugRecorder:
    """Thread-safe process-local ring buffer of memory debug traces."""

    def __init__(
        self,
        enabled: bool = True,
        max_traces: int = 50,
        max_raw_chars: int = 200_000,
    ) -> None:
        self.enabled = enabled
        self.max_traces = max(1, max_traces)
        self.max_raw_chars = max(0, max_raw_chars)
        self._trace_ids: deque[str] = deque()
        self._traces: dict[str, MemoryDebugTrace] = {}
        self._lock = RLock()

    def start_turn(self, turn: MemoryTurnInput) -> str | None:
        if not self.enabled:
            return None
        trace_id = trace_id_from_metadata(turn.metadata) or new_debug_trace_id()
        trace = MemoryDebugTrace(
            trace_id=trace_id,
            user_id=turn.user_id,
            session_id=turn.session_id,
            message_id=turn.new_message.id,
            new_message=turn.new_message,
            metadata={
                "conversation_context_count": len(turn.conversation_context),
                "context_state": (
                    turn.context_state.to_record() if turn.context_state else None
                ),
            },
        )
        self._upsert_trace(trace)
        return trace_id

    def record_extraction(
        self,
        trace_id: str | None,
        *,
        turn: MemoryTurnInput,
        prompt_messages: Sequence[ChatMessageParam] = (),
        raw_output: str | None = None,
        parse_status: str = "not_run",
        parse_error: str | None = None,
        parsed_batch: Any | None = None,
        validated_batch: Any | None = None,
        validation_errors: Sequence[str] = (),
        normalized_records: Sequence[MemoryRecord] = (),
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not trace_id:
            return
        truncated_prompt, prompt_truncated = self._truncate_prompt(prompt_messages)
        truncated_output, output_truncated = self._truncate_text(raw_output)
        info_metadata = dict(metadata or {})
        if prompt_truncated or output_truncated:
            info_metadata.update(
                {
                    "truncated": True,
                    "raw_prompt_truncated": prompt_truncated,
                    "raw_output_truncated": output_truncated,
                }
            )
        info = ExtractionDebugInfo(
            input_summary=_turn_input_summary(turn),
            prompt_messages=truncated_prompt,
            raw_output=truncated_output,
            raw_prompt_truncated=prompt_truncated,
            raw_output_truncated=output_truncated,
            parse_status=parse_status,
            parse_error=parse_error,
            parsed_candidate_counts=_batch_counts(parsed_batch),
            validated_candidate_counts=_batch_counts(validated_batch),
            validation_errors=list(validation_errors),
            normalized_records=list(normalized_records),
            metadata=info_metadata,
        )
        trace_metadata = {"truncated": True} if info_metadata.get("truncated") else None
        self._update_trace(
            trace_id,
            lambda trace: replace(
                trace,
                extraction=info,
                status=(
                    "extracted"
                    if parse_status in {"ok", "external"}
                    else "extraction_failed"
                ),
                metadata=(
                    {**dict(trace.metadata), **trace_metadata}
                    if trace_metadata
                    else trace.metadata
                ),
            ),
        )

    def record_retrieval(
        self,
        trace_id: str | None,
        *,
        active_memory_context,
        scoped_candidates: Sequence[MemoryRecord],
        search_request: MemorySearchRequest,
        search_result: MemorySearchResult,
        retrieval_request: MemoryRetrievalRequest,
        retrieval_result: MemoryRetrievalResult,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not trace_id:
            return
        info = RetrievalDebugInfo(
            active_memory_context=active_memory_context,
            scoped_candidates=list(scoped_candidates),
            search_request=search_request,
            search_result=search_result,
            retrieval_request=retrieval_request,
            retrieval_result=retrieval_result,
            memory_context=list(retrieval_result.memory_context),
            metadata=dict(metadata or {}),
        )
        self._update_trace(
            trace_id,
            lambda trace: replace(trace, retrieval=info, status="prepared"),
        )

    def record_write(
        self,
        trace_id: str | None,
        *,
        candidate_matching,
        write_plan,
        write_result,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not trace_id:
            return
        info = WriteDebugInfo(
            candidate_matching=candidate_matching,
            write_plan=write_plan,
            write_result=write_result,
            metadata=dict(metadata or {}),
        )
        self._update_trace(
            trace_id,
            lambda trace: replace(trace, write=info, status="committed"),
        )

    def mark_failed(
        self,
        trace_id: str | None,
        error: Exception | str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not trace_id:
            return
        error_text = str(error)
        self._update_trace(
            trace_id,
            lambda trace: replace(
                trace,
                status="failed",
                metadata={
                    **dict(trace.metadata),
                    **dict(metadata or {}),
                    "error": error_text,
                },
            ),
        )

    def get(self, trace_id: str) -> MemoryDebugTrace | None:
        with self._lock:
            return self._traces.get(trace_id)

    def list_traces(
        self,
        session_id: str | None = None,
        message_id: str | None = None,
        limit: int = 20,
    ) -> list[MemoryDebugTrace]:
        selected_limit = max(0, limit)
        with self._lock:
            traces = [
                self._traces[trace_id]
                for trace_id in reversed(self._trace_ids)
                if trace_id in self._traces
            ]
        filtered = [
            trace
            for trace in traces
            if (session_id is None or trace.session_id == session_id)
            and (message_id is None or trace.message_id == message_id)
        ]
        return filtered[:selected_limit]

    def _upsert_trace(self, trace: MemoryDebugTrace) -> None:
        with self._lock:
            if trace.trace_id not in self._traces:
                self._trace_ids.append(trace.trace_id)
            self._traces[trace.trace_id] = trace
            while len(self._trace_ids) > self.max_traces:
                old_trace_id = self._trace_ids.popleft()
                self._traces.pop(old_trace_id, None)

    def _update_trace(
        self,
        trace_id: str,
        update,
    ) -> None:
        with self._lock:
            trace = self._traces.get(trace_id)
            if trace is None:
                trace = MemoryDebugTrace(
                    trace_id=trace_id,
                    user_id=None,
                    session_id=None,
                    message_id=None,
                )
            self._traces[trace_id] = update(trace)
            if trace_id not in self._trace_ids:
                self._trace_ids.append(trace_id)
            while len(self._trace_ids) > self.max_traces:
                old_trace_id = self._trace_ids.popleft()
                self._traces.pop(old_trace_id, None)

    def _truncate_prompt(
        self,
        messages: Sequence[ChatMessageParam],
    ) -> tuple[list[ChatMessageParam], bool]:
        truncated = False
        output: list[ChatMessageParam] = []
        for message in messages:
            content, was_truncated = self._truncate_text(message.get("content"))
            truncated = truncated or was_truncated
            output.append({"role": message["role"], "content": content or ""})
        return output, truncated

    def _truncate_text(self, value: str | None) -> tuple[str | None, bool]:
        if value is None:
            return None, False
        if self.max_raw_chars <= 0:
            return "", bool(value)
        if len(value) <= self.max_raw_chars:
            return value, False
        return value[: self.max_raw_chars], True


def with_debug_trace_metadata(
    turn: MemoryTurnInput,
    trace_id: str | None,
) -> MemoryTurnInput:
    if not trace_id:
        return turn
    return replace(
        turn,
        metadata={**dict(turn.metadata), DEBUG_TRACE_ID_KEY: trace_id},
    )


def _turn_input_summary(turn: MemoryTurnInput) -> dict[str, Any]:
    return {
        "user_id": turn.user_id,
        "session_id": turn.session_id,
        "timezone": turn.timezone,
        "new_message": turn.new_message.to_record(),
        "conversation_context_count": len(turn.conversation_context),
        "conversation_context_message_ids": [
            message.id for message in turn.conversation_context
        ],
        "context_state": turn.context_state.to_record() if turn.context_state else None,
        "active_memory_counts": _active_context_counts(turn.active_memory_context),
    }


def _active_context_counts(active_context) -> dict[str, int]:
    if active_context is None:
        return {
            "event_memories": 0,
            "entity_memories": 0,
            "property_memories": 0,
            "other_memories": 0,
        }
    return {
        "event_memories": len(active_context.event_memories),
        "entity_memories": len(active_context.entity_memories),
        "property_memories": len(active_context.property_memories),
        "other_memories": len(active_context.other_memories),
    }


def _batch_counts(batch: Any | None) -> dict[str, int]:
    if batch is None:
        return {"events": 0, "entities": 0, "descriptions": 0, "properties": 0}
    descriptions = sum(len(event.descriptions) for event in batch.event_candidates)
    event_entities = sum(len(event.entities) for event in batch.event_candidates)
    top_properties = sum(len(entity.properties) for entity in batch.entity_candidates)
    event_properties = sum(
        len(entity.properties)
        for event in batch.event_candidates
        for entity in event.entities
    )
    return {
        "events": len(batch.event_candidates),
        "entities": len(batch.entity_candidates) + event_entities,
        "descriptions": descriptions,
        "properties": top_properties + event_properties,
    }
