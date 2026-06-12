"""Run real-LLM tests for LLM-backed memory reconciliation."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llm.config import LLMConfig
from llm.interfaces import ChatClient, ChatCompletionResult, ChatMessageParam
from llm.openai_client import OpenAIChatClient
from memory.models import (
    MemoryObjectRef,
    MemoryRecord,
    MemoryRecordType,
    MemorySearchHit,
    MemorySearchResult,
    MemorySourceRef,
)
from memory.reconciliation import LLMMemoryReconciler, MemoryReconciliationRequest
from memory.retrieval import CandidateMemoryMatcher
from memory.storage import InMemoryMemoryStore
from memory.writing import InMemoryMemoryWritePlanApplier, MemoryWriteRequest

USER_ID = "usr_reconciliation_real"
SESSION_ID = "ses_reconciliation_real"


@dataclass(frozen=True)
class ReconciliationRealCase:
    case_id: str
    title: str
    test_point: str
    seed_records: list[MemoryRecord]
    candidates: list[MemoryRecord]
    expected: dict[str, Any]


@dataclass
class TokenUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    raw_usage: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseResult:
    case: ReconciliationRealCase
    passed: bool
    checks: list[str]
    failures: list[str]
    duration_seconds: float
    token_usage: TokenUsage | None = None
    llm_input: list[dict[str, str]] = field(default_factory=list)
    llm_output: str | None = None
    write_plan: dict[str, Any] | None = None
    write_result: dict[str, Any] | None = None
    final_records: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


class RecordingChatClient:
    def __init__(self, inner: ChatClient) -> None:
        self.inner = inner
        self.last_usage: TokenUsage | None = None
        self.last_input: list[dict[str, str]] = []
        self.last_output: str | None = None

    def clear(self) -> None:
        self.last_usage = None
        self.last_input = []
        self.last_output = None

    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        self.last_input = [dict(message) for message in messages]
        self.last_output = None
        completion = self.inner.complete(
            messages=messages,
            model=model,
            temperature=temperature,
        )
        self.last_usage = _token_usage_from_raw(completion.usage)
        self.last_output = completion.content
        return completion


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run real LLM reconciliation tests")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument(
        "--report-path",
        default=None,
        help="Markdown report path. Defaults to a timestamped report.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 when any expectation fails",
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="case_ids",
        help="Run only the selected case id. Can be repeated.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env_file = Path(args.env_file)
    llm_config = LLMConfig.from_env(env_file)
    chat_client = RecordingChatClient(OpenAIChatClient(llm_config))
    cases = _selected_cases(build_cases(), args.case_ids)

    results = [
        _run_case(case, chat_client, model=llm_config.model)
        for case in cases
    ]

    report_path = Path(args.report_path) if args.report_path else _default_report_path()
    write_report(
        report_path,
        results=results,
        model=llm_config.model,
        base_url_configured=bool(llm_config.base_url),
    )
    passed_count = sum(1 for result in results if result.passed)
    print(f"report={report_path}")
    print(f"passed={passed_count}/{len(results)}")
    if args.strict and passed_count != len(results):
        return 1
    return 0


def build_cases() -> list[ReconciliationRealCase]:
    return [
        ReconciliationRealCase(
            case_id="reuse_existing_entity_property",
            title="复用已有实体和属性",
            test_point=(
                "当候选 entity/property 与已存记录文本和结构一致时，LLM 应复用旧记录，"
                "writer 不应创建重复实体或属性。"
            ),
            seed_records=[
                _record("ent_tea", "entity", "茉莉花茶", "old_ent_tea", {
                    "entity_type": "concept",
                }),
                _record("prop_less_sugar", "property", "用户偏好茉莉花茶少糖", "old_prop_less_sugar", {
                    "property_type": "preference",
                    "attached_to_record_id": "ent_tea",
                    "entity_client_id": "old_ent_tea",
                }),
            ],
            candidates=[
                _candidate("entity", "茉莉花茶", "cand_tea", {
                    "entity_type": "concept",
                }),
                _candidate("property", "用户偏好茉莉花茶少糖", "cand_less_sugar", {
                    "property_type": "preference",
                    "entity_client_id": "cand_tea",
                }),
            ],
            expected={
                "candidate_actions": {
                    "cand_tea": {"reuse"},
                    "cand_less_sugar": {"reuse", "ignore"},
                },
                "max_created_count": 0,
                "max_exact_duplicates": 1,
            },
        ),
        ReconciliationRealCase(
            case_id="attach_description_to_existing_event",
            title="将新描述挂到已有事件",
            test_point=(
                "当候选 event 命中已有 plan event，而 description 是新增细节时，"
                "LLM 应复用 event 并把 description attach 到旧 event。"
            ),
            seed_records=[
                _record("evt_shantou", "event", "汕头旅行计划", "old_evt_shantou", {
                    "event_type": "plan",
                    "summary": "用户计划去汕头旅游。",
                }),
            ],
            candidates=[
                _candidate("event", "汕头旅行计划", "cand_event", {
                    "event_type": "plan",
                    "summary": "用户计划下个月去汕头旅游并询问推荐。",
                }),
                _candidate("description", "用户计划下个月去汕头旅游并询问推荐", "cand_desc", {
                    "description_type": "detail",
                    "event_client_id": "cand_event",
                }),
            ],
            expected={
                "candidate_actions": {
                    "cand_event": {"reuse", "update"},
                    "cand_desc": {"attach", "create"},
                },
                "required_attached_text": "用户计划下个月去汕头旅游并询问推荐",
                "required_attached_target": "evt_shantou",
            },
        ),
        ReconciliationRealCase(
            case_id="same_turn_duplicate_entity",
            title="同轮重复实体去重",
            test_point=(
                "当同一轮候选里出现两个等价 entity 且无旧记录时，LLM 应避免创建两份，"
                "可以 create 一份并 reuse/ignore 另一份。"
            ),
            seed_records=[],
            candidates=[
                _candidate("entity", "汕头", "cand_shantou_a", {
                    "entity_type": "place",
                    "aliases": ["汕头市"],
                }),
                _candidate("entity", "汕头市", "cand_shantou_b", {
                    "entity_type": "place",
                    "aliases": ["汕头"],
                }),
            ],
            expected={
                "candidate_actions": {
                    "cand_shantou_a": {"create", "reuse", "ignore"},
                    "cand_shantou_b": {"create", "reuse", "ignore"},
                },
                "max_created_count": 1,
            },
        ),
        ReconciliationRealCase(
            case_id="update_changed_preference",
            title="更新变化的偏好属性",
            test_point=(
                "当用户偏好发生明确变化时，LLM 应选择 update 或 invalidate/flag_conflict，"
                "不能简单创建一个无关联重复属性。"
            ),
            seed_records=[
                _record("ent_user", "entity", "用户", "old_ent_user", {
                    "entity_type": "person",
                    "scope": "user",
                }),
                _record("prop_coffee_old", "property", "用户基本不喝咖啡", "old_prop_coffee", {
                    "property_type": "preference",
                    "attached_to_record_id": "ent_user",
                    "entity_client_id": "old_ent_user",
                }),
            ],
            candidates=[
                _candidate("entity", "用户", "cand_user", {
                    "entity_type": "person",
                    "scope": "user",
                }),
                _candidate("property", "用户现在每天早上喝咖啡", "cand_coffee_new", {
                    "property_type": "habit",
                    "entity_client_id": "cand_user",
                }),
            ],
            expected={
                "candidate_actions": {
                    "cand_user": {"reuse", "update"},
                    "cand_coffee_new": {"update", "invalidate", "flag_conflict", "attach"},
                },
                "preferred_actions": {"cand_coffee_new": {"update", "invalidate"}},
                "max_unattached_property_creates": 0,
            },
        ),
    ]


def _run_case(
    case: ReconciliationRealCase,
    chat_client: RecordingChatClient,
    model: str,
) -> CaseResult:
    chat_client.clear()
    store = InMemoryMemoryStore(case.seed_records)
    retrieval = CandidateMemoryMatcher().match(
        case.candidates,
        _search_result_from_store(store),
        user_id=USER_ID,
        session_id=SESSION_ID,
    )
    request = MemoryReconciliationRequest(
        candidates=case.candidates,
        retrieval=retrieval,
        user_id=USER_ID,
        session_id=SESSION_ID,
        metadata={"source": "reconciliation_real_test", "case_id": case.case_id},
    )
    start = time.perf_counter()
    try:
        plan = LLMMemoryReconciler(
            chat_client=chat_client,
            model=model,
            temperature=0.0,
            max_repair_attempts=1,
        ).reconcile(request)
        write_result = InMemoryMemoryWritePlanApplier(store).apply(
            MemoryWriteRequest(
                plan=plan,
                user_id=USER_ID,
                session_id=SESSION_ID,
            )
        )
        duration = time.perf_counter() - start
        final_records = store.list_records(user_id=USER_ID, session_id=SESSION_ID)
        checks, failures = _evaluate_case(case, plan.to_record(), write_result.to_record())
        return CaseResult(
            case=case,
            passed=not failures,
            checks=checks,
            failures=failures,
            duration_seconds=duration,
            token_usage=chat_client.last_usage,
            llm_input=chat_client.last_input,
            llm_output=chat_client.last_output,
            write_plan=plan.to_record(),
            write_result=write_result.to_record(),
            final_records=[record.to_record() for record in final_records],
        )
    except Exception as error:
        duration = time.perf_counter() - start
        return CaseResult(
            case=case,
            passed=False,
            checks=[],
            failures=[f"{type(error).__name__}: {error}"],
            duration_seconds=duration,
            token_usage=chat_client.last_usage,
            llm_input=chat_client.last_input,
            llm_output=chat_client.last_output,
            error=f"{type(error).__name__}: {error}",
        )


def _evaluate_case(
    case: ReconciliationRealCase,
    write_plan: dict[str, Any],
    write_result: dict[str, Any],
) -> tuple[list[str], list[str]]:
    checks: list[str] = []
    failures: list[str] = []
    operations = write_plan.get("operations", [])
    operations_by_candidate = {
        operation.get("candidate_id"): operation
        for operation in operations
        if isinstance(operation, dict)
    }

    for candidate_id, allowed_actions in case.expected.get("candidate_actions", {}).items():
        operation = operations_by_candidate.get(candidate_id)
        action = operation.get("action") if operation else None
        if action in allowed_actions:
            checks.append(f"{candidate_id} action={action}")
        else:
            failures.append(
                f"{candidate_id} expected action in {sorted(allowed_actions)}, got {action}"
            )

    max_created_count = case.expected.get("max_created_count")
    if isinstance(max_created_count, int):
        created_count = len(write_result.get("created_records", []))
        if created_count <= max_created_count:
            checks.append(f"created_count={created_count} <= {max_created_count}")
        else:
            failures.append(f"created_count={created_count} > {max_created_count}")

    max_exact_duplicates = case.expected.get("max_exact_duplicates")
    if isinstance(max_exact_duplicates, int):
        duplicates = _exact_duplicate_counts(write_result)
        offenders = {
            key: count for key, count in duplicates.items()
            if count > max_exact_duplicates
        }
        if not offenders:
            checks.append(f"exact duplicate count <= {max_exact_duplicates}")
        else:
            failures.append(f"exact duplicate offenders: {offenders}")

    required_attached_text = case.expected.get("required_attached_text")
    if isinstance(required_attached_text, str):
        attached = write_result.get("attached_records", [])
        matched = [
            record for record in attached
            if isinstance(record, dict) and record.get("text") == required_attached_text
        ]
        if matched:
            checks.append("required attached description was written")
        else:
            failures.append("required attached description was not written")
        target = case.expected.get("required_attached_target")
        if isinstance(target, str):
            if any(
                record.get("metadata", {}).get("attached_to_record_id") == target
                for record in matched
                if isinstance(record, dict)
            ):
                checks.append(f"attached target={target}")
            else:
                failures.append(f"attached description did not target {target}")

    preferred_actions = case.expected.get("preferred_actions")
    if isinstance(preferred_actions, dict):
        for candidate_id, preferred in preferred_actions.items():
            operation = operations_by_candidate.get(candidate_id)
            action = operation.get("action") if operation else None
            if action in preferred:
                checks.append(f"{candidate_id} preferred action={action}")
            else:
                failures.append(
                    f"{candidate_id} preferred action in {sorted(preferred)}, got {action}"
                )

    max_unattached_property_creates = case.expected.get("max_unattached_property_creates")
    if isinstance(max_unattached_property_creates, int):
        unattached = [
            record for record in write_result.get("created_records", [])
            if (
                isinstance(record, dict)
                and record.get("memory_type") == "property"
                and not record.get("metadata", {}).get("attached_to_record_id")
            )
        ]
        if len(unattached) <= max_unattached_property_creates:
            checks.append("no unexpected unattached property creates")
        else:
            failures.append(f"unexpected unattached property creates: {len(unattached)}")

    return checks, failures


def write_report(
    path: Path,
    *,
    results: list[CaseResult],
    model: str,
    base_url_configured: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    passed_count = sum(1 for result in results if result.passed)
    lines = [
        "# LLM Reconciliation Real Test Report",
        "",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        f"- Model: `{model}`",
        f"- Base URL configured: `{base_url_configured}`",
        f"- Passed: `{passed_count}/{len(results)}`",
        "",
        "## Summary",
        "",
        "| Case | Test Point | Result | Duration | Tokens |",
        "| --- | --- | --- | ---: | ---: |",
    ]
    for result in results:
        usage = result.token_usage.total_tokens if result.token_usage else None
        lines.append(
            "| "
            + " | ".join(
                [
                    result.case.case_id,
                    _escape_table(result.case.test_point),
                    "PASS" if result.passed else "FAIL",
                    f"{result.duration_seconds:.2f}s",
                    str(usage) if usage is not None else "-",
                ]
            )
            + " |"
        )
    for result in results:
        lines.extend(_case_report_lines(result))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _case_report_lines(result: CaseResult) -> list[str]:
    usage = result.token_usage
    lines = [
        "",
        f"## {result.case.case_id}: {result.case.title}",
        "",
        f"**Test point:** {result.case.test_point}",
        "",
        f"**Result:** {'PASS' if result.passed else 'FAIL'}",
        f"**Duration:** {result.duration_seconds:.2f}s",
    ]
    if usage:
        lines.append(
            "**Token usage:** "
            f"input={usage.input_tokens}, output={usage.output_tokens}, "
            f"total={usage.total_tokens}"
        )
    if result.checks:
        lines.extend(["", "### Checks", ""])
        lines.extend(f"- {check}" for check in result.checks)
    if result.failures:
        lines.extend(["", "### Failures", ""])
        lines.extend(f"- {failure}" for failure in result.failures)
    lines.extend(
        [
            "",
            "<details><summary>Seed records</summary>",
            "",
            "```json",
            json.dumps(
                [record.to_record() for record in result.case.seed_records],
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "</details>",
            "",
            "<details><summary>Candidates</summary>",
            "",
            "```json",
            json.dumps(
                [record.to_record() for record in result.case.candidates],
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "</details>",
        ]
    )
    for title, payload in (
        ("LLM input", result.llm_input),
        ("LLM output", result.llm_output),
        ("Write plan", result.write_plan),
        ("Write result", result.write_result),
        ("Final records", result.final_records),
    ):
        if payload is None or payload == []:
            continue
        lines.extend(
            [
                "",
                f"<details><summary>{title}</summary>",
                "",
                "```json",
                json.dumps(payload, ensure_ascii=False, indent=2)
                if not isinstance(payload, str)
                else payload,
                "```",
                "",
                "</details>",
            ]
        )
    return lines


def _selected_cases(
    cases: list[ReconciliationRealCase],
    case_ids: list[str] | None,
) -> list[ReconciliationRealCase]:
    if not case_ids:
        return cases
    selected = [case for case in cases if case.case_id in case_ids]
    missing = sorted(set(case_ids) - {case.case_id for case in selected})
    if missing:
        raise SystemExit(f"Unknown case ids: {', '.join(missing)}")
    return selected


def _search_result_from_store(store: InMemoryMemoryStore) -> MemorySearchResult:
    records = store.list_records(user_id=USER_ID, session_id=SESSION_ID)
    return MemorySearchResult(
        hits=[
            MemorySearchHit(
                object_ref=MemoryObjectRef(record.memory_type, record.id or ""),
                score=1.0,
                reason="real_reconciliation_seed",
                matched_text=record.text,
                record=record,
            )
            for record in records
            if record.id
        ],
        metadata={"search": "real_reconciliation_seed", "hit_count": len(records)},
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
        source_refs=[MemorySourceRef(source_type="message", source_id="msg_seed")],
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
        source_refs=[MemorySourceRef(source_type="message", source_id="msg_new")],
        metadata=merged_metadata,
    )


def _exact_duplicate_counts(write_result: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for bucket in ("created_records", "attached_records", "updated_records"):
        for record in write_result.get(bucket, []):
            if not isinstance(record, dict):
                continue
            key = f"{record.get('memory_type')}:{_normalize(record.get('text'))}"
            counts[key] = counts.get(key, 0) + 1
    return counts


def _normalize(value: object) -> str:
    return " ".join(str(value or "").split()).casefold()


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _default_report_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("tests") / "memory" / "reconciliation_real" / "reports" / f"{timestamp}.md"


def _token_usage_from_raw(raw_usage: dict[str, object]) -> TokenUsage:
    return TokenUsage(
        input_tokens=_first_int_field(raw_usage, ("prompt_tokens", "input_tokens")),
        output_tokens=_first_int_field(raw_usage, ("completion_tokens", "output_tokens")),
        total_tokens=_first_int_field(raw_usage, ("total_tokens",)),
        raw_usage=dict(raw_usage),
    )


def _first_int_field(
    raw_usage: dict[str, object],
    keys: tuple[str, ...],
) -> int | None:
    for key in keys:
        value = raw_usage.get(key)
        if isinstance(value, int):
            return value
    return None


if __name__ == "__main__":
    sys.exit(main())
