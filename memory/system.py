"""In-memory memory system composition."""

from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from .context import InMemoryActiveMemoryCache, NoopContextPolicy
from .extraction import NoopMemoryExtractor
from .interfaces import (
    ContextPolicy,
    MemoryExtractor,
    MemoryRetriever,
    MemoryStore,
    MemorySystem,
)
from .models import (
    ActiveMemoryContext,
    MemoryRecord,
    MemoryRetrievalRequest,
    MemoryRetrievalResult,
    MemoryTurnInput,
    MemoryTurnResult,
)
from .reconciliation import (
    DeterministicMemoryReconciler,
    MemoryReconciler,
    MemoryReconciliationRequest,
)
from .retrieval import CandidateMemoryRetriever, InMemoryMemoryRetriever
from .storage import InMemoryMemoryStore
from .writing import (
    InMemoryMemoryWritePlanApplier,
    MemoryWritePlanApplier,
    MemoryWriteRequest,
)


class InMemoryMemorySystem(MemorySystem):
    """Process-local memory runtime with replaceable components."""

    def __init__(
        self,
        store: MemoryStore | None = None,
        extractor: MemoryExtractor | None = None,
        retriever: MemoryRetriever | None = None,
        candidate_retriever: CandidateMemoryRetriever | None = None,
        reconciler: MemoryReconciler | None = None,
        write_applier: MemoryWritePlanApplier | None = None,
        active_cache: InMemoryActiveMemoryCache | None = None,
        context_policy: ContextPolicy | None = None,
    ) -> None:
        self.store = store or InMemoryMemoryStore()
        self.extractor = extractor or NoopMemoryExtractor()
        self.active_cache = active_cache or InMemoryActiveMemoryCache()
        self.context_policy = context_policy or NoopContextPolicy()
        self.retriever = retriever or InMemoryMemoryRetriever(self.store)
        self.candidate_retriever = (
            candidate_retriever or CandidateMemoryRetriever(self.store)
        )
        self.reconciler = reconciler or DeterministicMemoryReconciler()
        self.write_applier = (
            write_applier or InMemoryMemoryWritePlanApplier(self.store)
        )

    def process_turn(self, turn: MemoryTurnInput) -> MemoryTurnResult:
        active_context = turn.active_memory_context or self.active_cache.get(
            user_id=turn.user_id,
            session_id=turn.session_id,
        )
        enriched_turn = replace(turn, active_memory_context=active_context)

        candidate_records = list(self.extractor.extract(enriched_turn))
        scoped_records = [
            self._with_turn_scope(record=record, turn=enriched_turn)
            for record in candidate_records
        ]
        candidate_retrieval = self.candidate_retriever.retrieve_related(
            scoped_records,
            user_id=turn.user_id,
            session_id=turn.session_id,
        )
        write_plan = self.reconciler.reconcile(
            MemoryReconciliationRequest(
                candidates=scoped_records,
                retrieval=candidate_retrieval,
                user_id=turn.user_id,
                session_id=turn.session_id,
                metadata={"source": "process_turn"},
            )
        )
        write_result = self.write_applier.apply(
            MemoryWriteRequest(
                plan=write_plan,
                user_id=turn.user_id,
                session_id=turn.session_id,
                metadata={"source": "process_turn"},
            )
        )
        created_records = [
            *write_result.created_records,
            *write_result.attached_records,
        ]
        active_records = [
            *created_records,
            *write_result.reused_records,
        ]
        refreshed_context = self.active_cache.refresh(
            user_id=turn.user_id,
            session_id=turn.session_id,
            new_message_id=turn.new_message.id,
            active_context=active_context,
            memories=active_records,
        )
        retrieval_result = self.retrieve_context(
            MemoryRetrievalRequest(
                user_id=turn.user_id,
                session_id=turn.session_id,
                timezone=turn.timezone,
                conversation_context=turn.conversation_context,
                active_memory_context=refreshed_context,
                limit=8,
                metadata={"source": "process_turn"},
            )
        )
        policy_turn = replace(enriched_turn, active_memory_context=refreshed_context)
        context_actions = list(self.context_policy.plan_actions(policy_turn))

        return MemoryTurnResult(
            memory_context=retrieval_result.memory_context,
            context_actions=context_actions,
            created_memories=created_records,
            metadata={
                "memory_runtime": self.__class__.__name__,
                "memory_store": self.store.__class__.__name__,
                "active_memory_context": refreshed_context.to_record(),
                "retrieval": retrieval_result.metadata,
                "candidate_retrieval": candidate_retrieval.to_record(),
                "write_plan": write_plan.to_record(),
                "write_result": write_result.to_record(),
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
        return self.retriever.retrieve(enriched_request)

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
