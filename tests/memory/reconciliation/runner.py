"""Run local tests for deterministic memory reconciliation."""

from __future__ import annotations

import sys
import json
from collections.abc import Callable
from typing import Any

from llm.interfaces import ChatCompletionResult, ChatMessageParam
from memory.models import (
    MemoryObjectRef,
    MemoryRecord,
    MemoryRecordType,
    MemorySearchHit,
    MemorySearchResult,
    MemorySourceRef,
)
from memory.reconciliation import (
    DeterministicMemoryReconciler,
    LLMMemoryReconciler,
    MemoryReconciliationRequest,
    MemoryWritePlan,
)
from memory.retrieval import CandidateMemoryMatcher
from memory.storage import InMemoryMemoryStore

USER_ID = "usr_reconcile_test"
SESSION_ID = "ses_reconcile_test"


def main() -> int:
    tests: list[Callable[[], None]] = [
        test_reuses_direct_entity_match,
        test_creates_unmatched_entity,
        test_attaches_property_to_created_entity_candidate,
        test_attaches_property_to_reused_entity,
        test_property_does_not_reuse_parent_entity_text_match,
        test_reuses_direct_property_match,
        test_attaches_description_to_reused_event,
        test_llm_reconciler_reuses_direct_match,
        test_llm_reconciler_action_matrix_compiles_all_actions,
        test_llm_reconciler_repairs_invalid_decision,
        test_llm_reconciler_falls_back_on_bad_json,
        test_plan_is_provider_neutral_dict,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"passed={len(tests)}/{len(tests)}")
    return 0


def test_reuses_direct_entity_match() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea")]
    )
    candidates = [_candidate("entity", "茉莉花茶", client_id="cand_tea")]
    plan = _plan(store, candidates)
    operation = _operation(plan, "cand_tea")
    assert operation.action == "reuse"
    assert operation.existing_record_id == "ent_tea"
    assert operation.confidence == "high"
    assert operation.evidence


def test_creates_unmatched_entity() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea")]
    )
    candidates = [_candidate("entity", "蓝色收音机", client_id="cand_radio")]
    plan = _plan(store, candidates)
    operation = _operation(plan, "cand_radio")
    assert operation.action == "create"
    assert operation.existing_record_id is None
    assert operation.record is candidates[0]


def test_attaches_property_to_created_entity_candidate() -> None:
    store = InMemoryMemoryStore()
    candidates = [
        _candidate("entity", "蓝色收音机", client_id="cand_radio"),
        _candidate(
            "property",
            "收音机是蓝色的",
            client_id="cand_prop",
            metadata={"entity_client_id": "cand_radio"},
        ),
    ]
    plan = _plan(store, candidates)
    entity_operation = _operation(plan, "cand_radio")
    property_operation = _operation(plan, "cand_prop")
    assert entity_operation.action == "create"
    assert property_operation.action == "attach"
    assert property_operation.target_record_id is None
    assert property_operation.target_candidate_id == "cand_radio"
    assert property_operation.relation_type == "has_property"


def test_attaches_property_to_reused_entity() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea")]
    )
    candidates = [
        _candidate("entity", "茉莉花茶", client_id="cand_tea"),
        _candidate(
            "property",
            "用户偏好少糖",
            client_id="cand_prop",
            metadata={
                "entity_client_id": "cand_tea",
                "property_type": "preference",
            },
        ),
    ]
    plan = _plan(store, candidates)
    entity_operation = _operation(plan, "cand_tea")
    property_operation = _operation(plan, "cand_prop")
    assert entity_operation.action == "reuse"
    assert property_operation.action == "attach"
    assert property_operation.target_record_id == "ent_tea"
    assert property_operation.target_candidate_id == "cand_tea"
    assert property_operation.relation_type == "has_property"


def test_property_does_not_reuse_parent_entity_text_match() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea")]
    )
    candidates = [
        _candidate("entity", "茉莉花茶", client_id="cand_tea"),
        _candidate(
            "property",
            "用户偏好茉莉花茶少糖",
            client_id="cand_prop",
            metadata={
                "entity_client_id": "cand_tea",
                "property_type": "preference",
            },
        ),
    ]
    plan = _plan(store, candidates)
    property_operation = _operation(plan, "cand_prop")
    assert property_operation.action == "attach"
    assert property_operation.existing_record_id is None
    assert property_operation.target_record_id == "ent_tea"


def test_reuses_direct_property_match() -> None:
    store = InMemoryMemoryStore(
        [
            _record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea"),
            _record(
                "prop_sugar",
                "property",
                "用户偏好少糖",
                client_id="prop_sugar",
                metadata={
                    "entity_client_id": "ent_tea",
                    "property_type": "preference",
                },
            ),
        ]
    )
    candidates = [
        _candidate("entity", "茉莉花茶", client_id="cand_tea"),
        _candidate(
            "property",
            "用户偏好少糖",
            client_id="cand_prop",
            metadata={
                "entity_client_id": "cand_tea",
                "property_type": "preference",
            },
        ),
    ]
    plan = _plan(store, candidates)
    operation = _operation(plan, "cand_prop")
    assert operation.action == "reuse"
    assert operation.existing_record_id == "prop_sugar"


def test_attaches_description_to_reused_event() -> None:
    store = InMemoryMemoryStore(
        [
            _record(
                "evt_swim",
                "event",
                "游泳训练安排",
                client_id="evt_swim",
                metadata={"event_type": "plan"},
            )
        ]
    )
    candidates = [
        _candidate(
            "event",
            "游泳训练安排",
            client_id="cand_event",
            metadata={"event_type": "plan"},
        ),
        _candidate(
            "description",
            "用户每周三晚上练自由泳",
            client_id="cand_desc",
            metadata={"event_client_id": "cand_event"},
        ),
    ]
    plan = _plan(store, candidates)
    event_operation = _operation(plan, "cand_event")
    desc_operation = _operation(plan, "cand_desc")
    assert event_operation.action == "reuse"
    assert desc_operation.action == "attach"
    assert desc_operation.target_record_id == "evt_swim"
    assert desc_operation.relation_type == "has_description"


def test_llm_reconciler_reuses_direct_match() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea")]
    )
    candidates = [_candidate("entity", "茉莉花茶", client_id="cand_tea")]
    response = {
        "decisions": [
            {
                "candidate_id": "cand_tea",
                "action": "reuse",
                "existing_record_id": "ent_tea",
                "confidence": "high",
                "reason": "same entity",
            }
        ],
        "summary": "reuse existing entity",
    }
    plan = _llm_plan(store, candidates, [response])
    operation = _operation(plan, "cand_tea")
    assert operation.action == "reuse"
    assert operation.existing_record_id == "ent_tea"
    assert plan.metadata["reconciler"] == "llm"
    assert plan.metadata["summary"] == "reuse existing entity"


def test_llm_reconciler_action_matrix_compiles_all_actions() -> None:
    store = InMemoryMemoryStore(
        [
            _record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea"),
            _record(
                "prop_drink_old",
                "property",
                "用户每天喝咖啡",
                client_id="prop_drink_old",
                metadata={"property_type": "habit"},
            ),
            _record("ent_cat_a", "entity", "阿毛", client_id="ent_cat_a"),
            _record("ent_cat_b", "entity", "阿毛猫", client_id="ent_cat_b"),
            _record(
                "evt_old",
                "event",
                "旧门诊安排",
                client_id="evt_old",
                metadata={"event_type": "appointment"},
            ),
            _record(
                "prop_noise",
                "property",
                "临时噪音",
                client_id="prop_noise",
            ),
        ]
    )
    candidates = [
        _candidate("entity", "新的收音机", client_id="cand_create"),
        _candidate("entity", "茉莉花茶", client_id="cand_reuse"),
        _candidate(
            "property",
            "茉莉花茶少糖",
            client_id="cand_attach",
            metadata={"property_type": "preference"},
        ),
        _candidate(
            "property",
            "用户每天喝咖啡",
            client_id="cand_update",
            metadata={"property_type": "habit"},
        ),
        _candidate("entity", "阿毛", client_id="cand_merge"),
        _candidate(
            "event",
            "旧门诊安排",
            client_id="cand_invalidate",
            metadata={"event_type": "appointment"},
        ),
        _candidate(
            "property",
            "用户喜欢咖啡",
            client_id="cand_conflict",
            metadata={"property_type": "preference"},
        ),
        _candidate("property", "临时噪音", client_id="cand_ignore"),
    ]
    plan = _llm_plan(
        store,
        candidates,
        [
            {
                "decisions": [
                    {
                        "candidate_id": "cand_create",
                        "action": "create",
                        "reason": "new durable entity",
                    },
                    {
                        "candidate_id": "cand_reuse",
                        "action": "reuse",
                        "existing_record_id": "ent_tea",
                        "confidence": "high",
                        "reason": "same entity",
                    },
                    {
                        "candidate_id": "cand_attach",
                        "action": "attach",
                        "target_record_id": "ent_tea",
                        "relation_type": "has_property",
                        "reason": "new preference for known entity",
                    },
                    {
                        "candidate_id": "cand_update",
                        "action": "update",
                        "existing_record_id": "prop_drink_old",
                        "replacement_text": "用户最近改为每天喝咖啡",
                        "replacement_metadata": {"updated_from": "test"},
                        "reason": "candidate refines existing habit",
                    },
                    {
                        "candidate_id": "cand_merge",
                        "action": "merge",
                        "existing_record_id": "ent_cat_a",
                        "merge_source_record_ids": ["ent_cat_b"],
                        "reason": "same entity under a longer name",
                    },
                    {
                        "candidate_id": "cand_invalidate",
                        "action": "invalidate",
                        "invalidated_record_ids": ["evt_old"],
                        "reason": "old appointment no longer active",
                    },
                    {
                        "candidate_id": "cand_conflict",
                        "action": "flag_conflict",
                        "reason": "insufficient evidence to overwrite coffee preference",
                    },
                    {
                        "candidate_id": "cand_ignore",
                        "action": "ignore",
                        "existing_record_id": "prop_noise",
                        "reason": "not durable",
                    },
                ],
                "summary": "action matrix",
            }
        ],
    )

    assert plan.metadata["reconciler"] == "llm"
    assert plan.metadata["operation_count"] == len(candidates)
    assert _operation(plan, "cand_create").action == "create"
    assert _operation(plan, "cand_reuse").existing_record_id == "ent_tea"

    attach = _operation(plan, "cand_attach")
    assert attach.action == "attach"
    assert attach.target_record_id == "ent_tea"
    assert attach.relation_type == "has_property"

    update = _operation(plan, "cand_update")
    assert update.action == "update"
    assert update.existing_record_id == "prop_drink_old"
    assert update.replacement is not None
    assert update.replacement.text == "用户最近改为每天喝咖啡"
    assert update.replacement.metadata["updated_from"] == "test"

    merge = _operation(plan, "cand_merge")
    assert merge.action == "merge"
    assert merge.existing_record_id == "ent_cat_a"
    assert merge.merge_source_record_ids == ["ent_cat_b"]

    invalidate = _operation(plan, "cand_invalidate")
    assert invalidate.action == "invalidate"
    assert invalidate.invalidated_record_ids == ["evt_old"]

    conflict = _operation(plan, "cand_conflict")
    assert conflict.action == "flag_conflict"
    assert conflict.reason

    ignore = _operation(plan, "cand_ignore")
    assert ignore.action == "ignore"
    assert ignore.existing_record_id == "prop_noise"


def test_llm_reconciler_repairs_invalid_decision() -> None:
    store = InMemoryMemoryStore(
        [_record("ent_tea", "entity", "茉莉花茶", client_id="ent_tea")]
    )
    candidates = [_candidate("entity", "茉莉花茶", client_id="cand_tea")]
    plan = _llm_plan(
        store,
        candidates,
        [
            {
                "decisions": [
                    {
                        "candidate_id": "cand_tea",
                        "action": "reuse",
                        "existing_record_id": "missing",
                    }
                ]
            },
            {
                "decisions": [
                    {
                        "candidate_id": "cand_tea",
                        "action": "reuse",
                        "existing_record_id": "ent_tea",
                    }
                ]
            },
        ],
    )
    assert _operation(plan, "cand_tea").existing_record_id == "ent_tea"
    assert plan.metadata["repair_attempts"] == 1


def test_llm_reconciler_falls_back_on_bad_json() -> None:
    store = InMemoryMemoryStore()
    candidates = [_candidate("entity", "蓝色收音机", client_id="cand_radio")]
    plan = _llm_plan(store, candidates, ["not json"])
    operation = _operation(plan, "cand_radio")
    assert operation.action == "create"
    assert plan.metadata["reconciler"] == "llm_fallback"
    assert plan.metadata["llm_errors"]


def test_plan_is_provider_neutral_dict() -> None:
    store = InMemoryMemoryStore()
    candidates = [_candidate("entity", "蓝色收音机", client_id="cand_radio")]
    plan = _plan(store, candidates)
    payload = plan.to_record()
    assert payload["metadata"]["reconciler"] == "deterministic"
    assert payload["operations"][0]["action"] == "create"
    assert payload["operations"][0]["candidate_id"] == "cand_radio"


def _plan(
    store: InMemoryMemoryStore,
    candidates: list[MemoryRecord],
) -> MemoryWritePlan:
    retrieval = CandidateMemoryMatcher().match(
        candidates,
        _search_result_from_store(store),
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    return DeterministicMemoryReconciler().reconcile(
        MemoryReconciliationRequest(
            candidates=candidates,
            retrieval=retrieval,
            user_id=USER_ID,
            session_id=SESSION_ID,
        )
    )


def _llm_plan(
    store: InMemoryMemoryStore,
    candidates: list[MemoryRecord],
    responses: list[dict[str, Any] | str],
) -> MemoryWritePlan:
    retrieval = CandidateMemoryMatcher().match(
        candidates,
        _search_result_from_store(store),
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    return LLMMemoryReconciler(
        chat_client=_FakeChatClient(responses),
        max_repair_attempts=1,
    ).reconcile(
        MemoryReconciliationRequest(
            candidates=candidates,
            retrieval=retrieval,
            user_id=USER_ID,
            session_id=SESSION_ID,
        )
    )


def _search_result_from_store(store: InMemoryMemoryStore) -> MemorySearchResult:
    records = store.list_records(user_id=USER_ID, session_id=SESSION_ID)
    return MemorySearchResult(
        hits=[
            MemorySearchHit(
                object_ref=MemoryObjectRef(record.memory_type, record.id or ""),
                score=1.0,
                reason="test_store_fixture",
                matched_text=record.text,
                record=record,
            )
            for record in records
            if record.id
        ],
        metadata={"search": "test_store_fixture", "hit_count": len(records)},
    )


def _record(
    record_id: str,
    memory_type: MemoryRecordType,
    text: str,
    client_id: str,
    metadata: dict[str, Any] | None = None,
) -> MemoryRecord:
    merged_metadata = {
        "candidate_client_id": client_id,
        "user_id": USER_ID,
        "session_id": SESSION_ID,
    }
    merged_metadata.update(metadata or {})
    return MemoryRecord(
        id=record_id,
        memory_type=memory_type,
        text=text,
        source_refs=[MemorySourceRef(source_type="message", source_id="msg_old")],
        metadata=merged_metadata,
    )


def _candidate(
    memory_type: MemoryRecordType,
    text: str,
    client_id: str,
    metadata: dict[str, Any] | None = None,
) -> MemoryRecord:
    merged_metadata = {"candidate_client_id": client_id}
    merged_metadata.update(metadata or {})
    return MemoryRecord(
        id=None,
        memory_type=memory_type,
        text=text,
        metadata=merged_metadata,
    )


def _operation(plan: MemoryWritePlan, candidate_id: str):
    for operation in plan.operations:
        if operation.candidate_id == candidate_id:
            return operation
    raise AssertionError(f"operation {candidate_id!r} not found")


class _FakeChatClient:
    def __init__(self, responses: list[dict[str, Any] | str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[ChatMessageParam]] = []

    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        self.calls.append(messages)
        if not self._responses:
            raise AssertionError("fake chat client has no response left")
        response = self._responses.pop(0)
        content = response if isinstance(response, str) else json.dumps(response)
        return ChatCompletionResult(content=content, model=model, usage={"fake": 1})


if __name__ == "__main__":
    sys.exit(main())
