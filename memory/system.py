"""In-memory memory system composition."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Sequence

from .context import InMemoryActiveMemoryCache, NoopContextPolicy
from .debug import MemoryDebugRecorder, trace_id_from_metadata, with_debug_trace_metadata
from .extraction import NoopMemoryExtractor
from .interfaces import (
    ContextPolicy,
    MemoryExtractor,
    MemoryContextRetriever,
    MemoryStore,
    MemorySystem,
)
from .models import (
    ActiveMemoryContext,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemorySearchRequest,
    MemoryTurnCommitInput,
    MemoryTurnInput,
    MemoryTurnPrepareResult,
    MemoryTurnResult,
    MemoryTurnSnapshot,
)
from .persistence import MemoryWriteResultPersistenceSync
from .reconciliation import (
    DeterministicMemoryReconciler,
    MemoryReconciler,
    MemoryReconciliationRequest,
)
from .retrieval import CandidateMemoryMatcher, SimpleMemoryContextRetriever
from .storage import InMemoryMemoryStore
from .writing import (
    InMemoryMemoryWritePlanApplier,
    MemoryWritePlanApplier,
    MemoryWriteRequest,
)

LOGGER = logging.getLogger(__name__)


class InMemoryMemorySystem(MemorySystem):
    """Process-local memory runtime with replaceable components."""

    def __init__(
        self,
        store: MemoryStore | None = None,
        extractor: MemoryExtractor | None = None,
        context_retriever: MemoryContextRetriever | None = None,
        candidate_matcher: CandidateMemoryMatcher | None = None,
        reconciler: MemoryReconciler | None = None,
        write_applier: MemoryWritePlanApplier | None = None,
        persistence_sync: MemoryWriteResultPersistenceSync | None = None,
        active_cache: InMemoryActiveMemoryCache | None = None,
        context_policy: ContextPolicy | None = None,
        debug_recorder: MemoryDebugRecorder | None = None,
    ) -> None:
        self.store = store or InMemoryMemoryStore()
        self.extractor = extractor or NoopMemoryExtractor()
        self.active_cache = active_cache or InMemoryActiveMemoryCache()
        self.context_policy = context_policy or NoopContextPolicy()
        self.context_retriever = (
            context_retriever or SimpleMemoryContextRetriever(self.store)
        )
        self.candidate_matcher = candidate_matcher or CandidateMemoryMatcher()
        self.reconciler = reconciler or DeterministicMemoryReconciler()
        self.write_applier = (
            write_applier or InMemoryMemoryWritePlanApplier(self.store)
        )
        self.persistence_sync = persistence_sync
        self.debug_recorder = debug_recorder

    def prepare_turn(self, turn: MemoryTurnInput) -> MemoryTurnPrepareResult:
        trace_id = self._start_debug_trace(turn)
        debug_turn = with_debug_trace_metadata(turn, trace_id)
        try:
            return self._prepare_turn(debug_turn, trace_id)
        except Exception as error:
            if self.debug_recorder is not None:
                self.debug_recorder.mark_failed(trace_id, error)
            raise

    def _prepare_turn(
        self,
        turn: MemoryTurnInput,
        trace_id: str | None,
    ) -> MemoryTurnPrepareResult:
        active_context = turn.active_memory_context or self.active_cache.get(
            user_id=turn.user_id,
            session_id=turn.session_id,
        )
        enriched_turn = replace(turn, active_memory_context=active_context)

        candidate_records = list(self.extractor.extract(enriched_turn))
        self._record_external_extraction_if_needed(
            trace_id=trace_id,
            turn=enriched_turn,
            records=candidate_records,
        )
        scoped_records = [
            self._with_turn_scope(record=record, turn=enriched_turn)
            for record in candidate_records
        ]

        search_request = MemorySearchRequest(
            user_id=turn.user_id,
            session_id=turn.session_id,
            query=self._search_query(enriched_turn, scoped_records, active_context),
            timezone=turn.timezone,
            candidates=scoped_records,
            active_memory_context=active_context,
            limit=32,
            metadata={
                **dict(turn.metadata),
                "source": "prepare_turn",
                "debug_trace_id": trace_id,
            },
        )
        search_result = self.context_retriever.search(search_request)
        retrieval_request = MemoryRetrievalRequest(
            user_id=turn.user_id,
            session_id=turn.session_id,
            query=search_request.query,
            timezone=turn.timezone,
            conversation_context=turn.conversation_context,
            active_memory_context=active_context,
            limit=8,
            metadata={
                **dict(turn.metadata),
                "source": "prepare_turn",
                "debug_trace_id": trace_id,
            },
        )
        retrieval_result = self.context_retriever.retrieve_from_search(
            search_result,
            retrieval_request,
        )
        self._record_retrieval_debug(
            trace_id=trace_id,
            active_context=active_context,
            scoped_records=scoped_records,
            search_request=search_request,
            search_result=search_result,
            retrieval_request=retrieval_request,
            retrieval_result=retrieval_result,
        )
        policy_turn = replace(enriched_turn, active_memory_context=active_context)
        context_actions = list(self.context_policy.plan_actions(policy_turn))
        snapshot = MemoryTurnSnapshot(
            turn=enriched_turn,
            candidates=scoped_records,
            search_result=search_result,
            memory_context=retrieval_result.memory_context,
            retrieved_memories=retrieval_result.records,
            active_memory_context=active_context,
            metadata={
                "source": "prepare_turn",
                "debug_trace_id": trace_id,
                "candidate_count": len(scoped_records),
                "search": search_result.metadata,
                "retrieval": retrieval_result.metadata,
            },
        )
        return MemoryTurnPrepareResult(
            snapshot=snapshot,
            memory_context=retrieval_result.memory_context,
            context_actions=context_actions,
            metadata=snapshot.metadata,
        )

    def commit_turn(self, commit: MemoryTurnCommitInput) -> MemoryTurnResult:
        return self._commit_turn(commit)

    def commit_turn_with_writers(
        self,
        commit: MemoryTurnCommitInput,
        write_applier: MemoryWritePlanApplier,
        persistence_sync: MemoryWriteResultPersistenceSync | None,
    ) -> MemoryTurnResult:
        return self._commit_turn(
            commit,
            write_applier=write_applier,
            persistence_sync=persistence_sync,
        )

    def _commit_turn(
        self,
        commit: MemoryTurnCommitInput,
        write_applier: MemoryWritePlanApplier | None = None,
        persistence_sync: MemoryWriteResultPersistenceSync | None = None,
    ) -> MemoryTurnResult:
        snapshot = commit.snapshot
        turn = snapshot.turn
        scoped_records = snapshot.candidates
        selected_write_applier = write_applier or self.write_applier
        selected_persistence_sync = (
            persistence_sync if persistence_sync is not None else self.persistence_sync
        )
        active_context = snapshot.active_memory_context or self.active_cache.get(
            user_id=turn.user_id,
            session_id=turn.session_id,
        )
        candidate_retrieval = self.candidate_matcher.match(
            scoped_records,
            snapshot.search_result,
            user_id=turn.user_id,
            session_id=turn.session_id,
        )
        write_plan = self.reconciler.reconcile(
            MemoryReconciliationRequest(
                candidates=scoped_records,
                retrieval=candidate_retrieval,
                user_id=turn.user_id,
                session_id=turn.session_id,
                metadata={
                    "source": "commit_turn",
                    "assistant_message_id": (
                        commit.assistant_message.id
                        if commit.assistant_message is not None
                        else None
                    ),
                    **dict(commit.metadata),
                },
            )
        )
        write_result = selected_write_applier.apply(
            MemoryWriteRequest(
                plan=write_plan,
                user_id=turn.user_id,
                session_id=turn.session_id,
                metadata={
                    "source": "commit_turn",
                    "assistant_message_id": (
                        commit.assistant_message.id
                        if commit.assistant_message is not None
                        else None
                    ),
                    **dict(commit.metadata),
                },
            )
        )
        persistent_write_metadata = self._sync_persistent_memory(
            write_result,
            persistence_sync=selected_persistence_sync,
            strict=persistence_sync is not None,
        )
        created_records = [
            *write_result.created_records,
            *write_result.attached_records,
        ]
        active_records = [
            *created_records,
            *write_result.reused_records,
            *self._retrieved_active_records(snapshot.retrieved_memories),
        ]
        refreshed_context = self.active_cache.refresh(
            user_id=turn.user_id,
            session_id=turn.session_id,
            new_message_id=turn.new_message.id,
            active_context=active_context,
            memories=active_records,
        )
        policy_turn = replace(turn, active_memory_context=refreshed_context)
        context_actions = list(self.context_policy.plan_actions(policy_turn))

        return MemoryTurnResult(
            memory_context=snapshot.memory_context,
            context_actions=context_actions,
            created_memories=created_records,
            updated_memories=write_result.reused_records,
            metadata={
                "memory_runtime": self.__class__.__name__,
                "memory_store": self.store.__class__.__name__,
                "active_memory_context": refreshed_context.to_record(),
                "snapshot": snapshot.to_record(),
                "candidate_matching": candidate_retrieval.to_record(),
                "write_plan": write_plan.to_record(),
                "write_result": write_result.to_record(),
                "persistent_write": persistent_write_metadata,
            },
        )

    def retrieve_context(
        self,
        request: MemoryRetrievalRequest,
    ) -> MemoryRetrievalResult:
        active_context = request.active_memory_context or self.active_cache.get(
            user_id=request.user_id,
            session_id=request.session_id,
        )
        enriched_request = replace(request, active_memory_context=active_context)
        return self.context_retriever.retrieve(enriched_request)

    def seed_records(
        self,
        records: Sequence[MemoryRecord],
    ) -> Sequence[MemoryRecord]:
        return self.store.save_records(records)

    def get_active_context(
        self,
        user_id: str | None,
        session_id: str | None,
    ) -> ActiveMemoryContext:
        return self.active_cache.get(user_id=user_id, session_id=session_id)

    def _with_turn_scope(
        self,
        record: MemoryRecord,
        turn: MemoryTurnInput,
    ) -> MemoryRecord:
        metadata = dict(record.metadata)
        if turn.user_id is not None:
            metadata.setdefault("user_id", turn.user_id)
        if turn.session_id is not None:
            metadata.setdefault("session_id", turn.session_id)
        if turn.timezone is not None:
            metadata.setdefault("timezone", turn.timezone)
        metadata.setdefault("created_from_message_id", turn.new_message.id)
        return replace(record, metadata=metadata)

    def _search_query(
        self,
        turn: MemoryTurnInput,
        candidates: Sequence[MemoryRecord],
        active_context: ActiveMemoryContext,
    ) -> str:
        parts = [turn.new_message.content]
        parts.extend(record.text for record in candidates if record.text)
        parts.extend(record.text for record in active_context.event_memories)
        parts.extend(record.text for record in active_context.entity_memories)
        parts.extend(record.text for record in active_context.property_memories)
        parts.extend(record.text for record in active_context.other_memories)
        return " ".join(part.strip() for part in parts if part and part.strip())

    def _retrieved_active_records(
        self,
        records: Sequence[MemoryRecord],
    ) -> list[MemoryRecord]:
        return [
            record
            for record in records
            if record.memory_type in {"event", "entity"}
        ]

    def _start_debug_trace(self, turn: MemoryTurnInput) -> str | None:
        if self.debug_recorder is None:
            return trace_id_from_metadata(turn.metadata)
        return self.debug_recorder.start_turn(turn)

    def _record_external_extraction_if_needed(
        self,
        trace_id: str | None,
        turn: MemoryTurnInput,
        records: Sequence[MemoryRecord],
    ) -> None:
        if self.debug_recorder is None or not trace_id:
            return
        trace = self.debug_recorder.get(trace_id)
        if trace is not None and trace.extraction is not None:
            return
        self.debug_recorder.record_extraction(
            trace_id,
            turn=turn,
            parse_status="external",
            normalized_records=records,
            metadata={"extractor": self.extractor.__class__.__name__},
        )

    def _record_retrieval_debug(
        self,
        trace_id: str | None,
        active_context: ActiveMemoryContext,
        scoped_records: Sequence[MemoryRecord],
        search_request: MemorySearchRequest,
        search_result,
        retrieval_request: MemoryRetrievalRequest,
        retrieval_result: MemoryRetrievalResult,
    ) -> None:
        if self.debug_recorder is None:
            return
        self.debug_recorder.record_retrieval(
            trace_id,
            active_memory_context=active_context,
            scoped_candidates=scoped_records,
            search_request=search_request,
            search_result=search_result,
            retrieval_request=retrieval_request,
            retrieval_result=retrieval_result,
            metadata={
                "context_retriever": self.context_retriever.__class__.__name__,
                "search_hit_count": len(search_result.hits),
                "memory_context_count": len(retrieval_result.memory_context),
            },
        )

    def _sync_persistent_memory(
        self,
        write_result: "MemoryWriteResult",
        persistence_sync: MemoryWriteResultPersistenceSync | None = None,
        strict: bool = False,
    ) -> dict[str, object] | None:
        selected_persistence_sync = persistence_sync
        if selected_persistence_sync is None:
            return None
        try:
            return selected_persistence_sync.sync(write_result).to_record()
        except Exception as error:
            if strict:
                raise
            LOGGER.warning("Persistent memory sync failed: %s", error)
            return {
                "error": str(error),
                "sync": selected_persistence_sync.__class__.__name__,
            }
