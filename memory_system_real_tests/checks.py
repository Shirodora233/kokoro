"""Expectation checks for real memory-system integration tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from memory.models import MemoryRecord, MemoryTurnResult

from .cases import MemorySystemTestScenario, StoreSignal, WriteSignal
from .recording import TokenUsage


@dataclass(frozen=True)
class CheckResult:
    label: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class TurnRun:
    turn_index: int
    result: MemoryTurnResult | None = None
    error: str | None = None
    duration_seconds: float | None = None
    token_usage: TokenUsage | None = None
    llm_input: list[dict[str, str]] = field(default_factory=list)
    llm_output: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class ScenarioResult:
    scenario: MemorySystemTestScenario
    turns: list[TurnRun]
    final_records: list[MemoryRecord]
    active_context: dict[str, Any] | None = None
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(turn.passed for turn in self.turns) and all(
            check.passed for check in self.checks
        )


def evaluate_scenario(
    scenario: MemorySystemTestScenario,
    turns: list[TurnRun],
    final_records: list[MemoryRecord],
    active_context: dict[str, Any] | None,
) -> ScenarioResult:
    checks: list[CheckResult] = []
    checks.extend(
        _evaluate_store_signal(signal, final_records)
        for signal in scenario.expected_store_signals
    )
    checks.extend(
        _evaluate_write_signal(signal, turns)
        for signal in scenario.expected_write_signals
    )
    checks.extend(_invariant_checks(turns, final_records))
    return ScenarioResult(
        scenario=scenario,
        turns=turns,
        final_records=final_records,
        active_context=active_context,
        checks=checks,
    )


def _evaluate_store_signal(
    signal: StoreSignal,
    records: list[MemoryRecord],
) -> CheckResult:
    failures: list[str] = []
    if signal.min_records is not None and len(records) < signal.min_records:
        failures.append(f"expected at least {signal.min_records}, got {len(records)}")
    if signal.required_all_types:
        missing_types = [
            memory_type
            for memory_type in signal.required_all_types
            if not any(record.memory_type == memory_type for record in records)
        ]
        if missing_types:
            failures.append(f"missing required types {missing_types}")
    if signal.any_text_contains and not _contains_any(records, signal.any_text_contains):
        failures.append(f"missing any text signal in {signal.any_text_contains}")
    if signal.all_text_contains:
        missing = _missing_text_signals(records, signal.all_text_contains)
        if missing:
            failures.append(f"missing text signals {missing}")
    if signal.max_exact_duplicates is not None:
        duplicates = _exact_duplicate_keys(records, signal.max_exact_duplicates)
        if duplicates:
            failures.append(f"duplicate keys above limit: {duplicates}")

    if failures:
        return CheckResult(signal.label, False, "; ".join(failures))
    return CheckResult(signal.label, True, "ok")


def _evaluate_write_signal(
    signal: WriteSignal,
    turns: list[TurnRun],
) -> CheckResult:
    failures: list[str] = []
    actions = _write_actions(turns)
    if signal.required_actions:
        missing = [action for action in signal.required_actions if action not in actions]
        if missing:
            failures.append(f"missing write actions {missing}; got {sorted(actions)}")

    created_count = sum(_write_metadata(turn).get("created_count", 0) for turn in turns)
    attached_count = sum(_write_metadata(turn).get("attached_count", 0) for turn in turns)
    failed_count = sum(_write_metadata(turn).get("failed_count", 0) for turn in turns)

    if (
        signal.min_created_records is not None
        and created_count < signal.min_created_records
    ):
        failures.append(
            f"expected created_count >= {signal.min_created_records}, got {created_count}"
        )
    if (
        signal.min_attached_records is not None
        and attached_count < signal.min_attached_records
    ):
        failures.append(
            f"expected attached_count >= {signal.min_attached_records}, got {attached_count}"
        )
    if signal.expect_no_failures and failed_count:
        failures.append(f"expected no failed write operations, got {failed_count}")

    if failures:
        return CheckResult(signal.label, False, "; ".join(failures))
    return CheckResult(signal.label, True, "ok")


def _invariant_checks(
    turns: list[TurnRun],
    records: list[MemoryRecord],
) -> list[CheckResult]:
    return [
        _all_turns_have_system_metadata(turns),
        _all_records_have_scope(records),
        _relation_records_have_resolved_endpoints(records),
        _no_forbidden_metadata_keys(records),
        _all_records_have_source_refs(records),
    ]


def _write_actions(turns: list[TurnRun]) -> set[str]:
    actions: set[str] = set()
    for turn in turns:
        if turn.result is None:
            continue
        plan = turn.result.metadata.get("write_plan", {})
        if not isinstance(plan, dict):
            continue
        operations = plan.get("operations", [])
        if not isinstance(operations, list):
            continue
        for operation in operations:
            if isinstance(operation, dict) and isinstance(operation.get("action"), str):
                actions.add(operation["action"])
    return actions


def _write_metadata(turn: TurnRun) -> dict[str, int]:
    if turn.result is None:
        return {}
    payload = turn.result.metadata.get("write_result", {})
    if not isinstance(payload, dict):
        return {}
    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        return {}
    return {key: value for key, value in metadata.items() if isinstance(value, int)}


def _all_turns_have_system_metadata(turns: list[TurnRun]) -> CheckResult:
    missing: list[int] = []
    for turn in turns:
        if turn.result is None:
            continue
        metadata = turn.result.metadata
        for key in ("candidate_retrieval", "write_plan", "write_result"):
            if key not in metadata:
                missing.append(turn.turn_index)
                break
    if missing:
        return CheckResult(
            "每轮结果包含系统链路 metadata",
            False,
            f"missing metadata on turns {missing}",
        )
    return CheckResult("每轮结果包含系统链路 metadata", True, "ok")


def _all_records_have_scope(records: list[MemoryRecord]) -> CheckResult:
    missing: list[str] = []
    for record in records:
        if record.source_refs and record.source_refs[0].source_type == "manual_seed":
            continue
        if "user_id" not in record.metadata or "session_id" not in record.metadata:
            missing.append(record.id or record.text)
    if missing:
        return CheckResult("写入记录包含 user/session scope", False, str(missing))
    return CheckResult("写入记录包含 user/session scope", True, "ok")


def _relation_records_have_resolved_endpoints(
    records: list[MemoryRecord],
) -> CheckResult:
    failures: list[str] = []
    for record in records:
        if record.memory_type == "link":
            if "from_record_id" not in record.metadata:
                failures.append(f"{record.id} missing from_record_id")
            if "to_record_id" not in record.metadata:
                failures.append(f"{record.id} missing to_record_id")
        if record.memory_type == "time_link":
            if "target_record_id" not in record.metadata:
                failures.append(f"{record.id} missing target_record_id")
            if "time_ref_record_id" not in record.metadata:
                failures.append(f"{record.id} missing time_ref_record_id")
    if failures:
        return CheckResult("link/time_link 端点已解析", False, "; ".join(failures))
    return CheckResult("link/time_link 端点已解析", True, "ok")


def _no_forbidden_metadata_keys(records: list[MemoryRecord]) -> CheckResult:
    forbidden = {"canonical_key", "dedup_key"}
    found: list[str] = []
    for record in records:
        found.extend(key for key in forbidden if key in record.metadata)
    if found:
        return CheckResult(
            "metadata 不包含 canonical_key/dedup_key",
            False,
            f"found {sorted(set(found))}",
        )
    return CheckResult("metadata 不包含 canonical_key/dedup_key", True, "ok")


def _all_records_have_source_refs(records: list[MemoryRecord]) -> CheckResult:
    missing = [record.id or record.text for record in records if not record.source_refs]
    if missing:
        return CheckResult(
            "所有记录都有 source_refs",
            False,
            f"{len(missing)} records missing source_refs",
        )
    return CheckResult("所有记录都有 source_refs", True, "ok")


def _contains_any(records: list[MemoryRecord], needles: tuple[str, ...]) -> bool:
    text = "\n".join(_searchable_text(record) for record in records).casefold()
    return any(needle.casefold() in text for needle in needles)


def _missing_text_signals(
    records: list[MemoryRecord],
    needles: tuple[str, ...],
) -> list[str]:
    text = "\n".join(_searchable_text(record) for record in records).casefold()
    return [needle for needle in needles if needle.casefold() not in text]


def _searchable_text(record: MemoryRecord) -> str:
    source_quotes = [source_ref.quote or "" for source_ref in record.source_refs]
    return "\n".join(
        [
            record.text,
            *source_quotes,
            json.dumps(record.metadata, ensure_ascii=False),
        ]
    )


def _exact_duplicate_keys(
    records: list[MemoryRecord],
    limit: int,
) -> list[str]:
    counts: dict[tuple[str, str], int] = {}
    for record in records:
        if record.memory_type in {"link", "time_link"}:
            continue
        key = (record.memory_type, " ".join(record.text.split()).casefold())
        counts[key] = counts.get(key, 0) + 1
    return [
        f"{memory_type}:{text}={count}"
        for (memory_type, text), count in sorted(counts.items())
        if count > limit
    ]
