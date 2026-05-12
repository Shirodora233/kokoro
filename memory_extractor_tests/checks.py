"""Expectation checks for extractor integration tests."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from memory.models import MemoryRecord
from memory.extraction.validation import (
    ALLOWED_CERTAINTY,
    ALLOWED_TIME_KINDS,
    ALLOWED_TIME_ROLES,
    ALLOWED_TIMELINE_KINDS,
    TIME_KIND_REQUIRED_FIELDS,
    TIME_REF_BASE_FIELDS,
)

from .cases import ExpectedSignal, ExtractorTestCase


@dataclass(frozen=True)
class CheckResult:
    label: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class CaseResult:
    case: ExtractorTestCase
    records: list[MemoryRecord] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None
    duration_seconds: float | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(check.passed for check in self.checks)


def evaluate_case(
    case: ExtractorTestCase,
    records: list[MemoryRecord],
    duration_seconds: float,
) -> CaseResult:
    checks = [_evaluate_signal(signal, records) for signal in case.expected_signals]
    checks.extend(_invariant_checks(case, records))
    return CaseResult(
        case=case,
        records=records,
        checks=checks,
        duration_seconds=duration_seconds,
    )


def failed_case(
    case: ExtractorTestCase,
    error: Exception,
    duration_seconds: float,
) -> CaseResult:
    return CaseResult(
        case=case,
        checks=[],
        error=f"{type(error).__name__}: {error}",
        duration_seconds=duration_seconds,
    )


def _evaluate_signal(
    signal: ExpectedSignal,
    records: list[MemoryRecord],
) -> CheckResult:
    failures: list[str] = []
    if signal.min_records is not None and len(records) < signal.min_records:
        failures.append(f"expected at least {signal.min_records}, got {len(records)}")
    if signal.max_records is not None and len(records) > signal.max_records:
        failures.append(f"expected at most {signal.max_records}, got {len(records)}")
    if signal.required_types and not _has_any_type(records, signal.required_types):
        failures.append(f"missing any type in {signal.required_types}")
    if signal.required_all_types:
        missing_types = [
            memory_type
            for memory_type in signal.required_all_types
            if not _has_any_type(records, (memory_type,))
        ]
        if missing_types:
            failures.append(f"missing required types {missing_types}")
    if signal.any_text_contains and not _contains_any(records, signal.any_text_contains):
        failures.append(f"missing text signal in {signal.any_text_contains}")

    if failures:
        return CheckResult(signal.label, False, "; ".join(failures))
    return CheckResult(signal.label, True, "ok")


def _invariant_checks(
    case: ExtractorTestCase,
    records: list[MemoryRecord],
) -> list[CheckResult]:
    return [
        _no_forbidden_metadata_keys(records),
        _all_records_have_source_refs(records),
        _source_quotes_match_messages(case, records),
        _time_refs_have_required_metadata(records),
        _time_links_reference_existing_candidates(records),
        _events_have_time_links(records),
        _all_records_have_text(records),
    ]


def _has_any_type(records: list[MemoryRecord], types: tuple[str, ...]) -> bool:
    return any(record.memory_type in types for record in records)


def _contains_any(records: list[MemoryRecord], needles: tuple[str, ...]) -> bool:
    text = "\n".join(_searchable_text(record) for record in records).casefold()
    return any(needle.casefold() in text for needle in needles)


def _searchable_text(record: MemoryRecord) -> str:
    source_quotes = [
        source_ref.quote or ""
        for source_ref in record.source_refs
    ]
    return "\n".join(
        [
            record.text,
            *source_quotes,
            json.dumps(record.metadata, ensure_ascii=False),
        ]
    )


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
    missing = [record.text for record in records if not record.source_refs]
    if missing:
        return CheckResult(
            "所有候选都有 source_refs",
            False,
            f"{len(missing)} records missing source_refs",
        )
    return CheckResult("所有候选都有 source_refs", True, "ok")


def _source_quotes_match_messages(
    case: ExtractorTestCase,
    records: list[MemoryRecord],
) -> CheckResult:
    messages = {
        message.id: message.content
        for message in [*case.turn.conversation_context, case.turn.new_message]
    }
    mismatches: list[str] = []
    for record in records:
        for source_ref in record.source_refs:
            if not source_ref.quote:
                continue
            source_content = messages.get(source_ref.source_id)
            if source_content is None:
                mismatches.append(f"unknown source {source_ref.source_id}")
                continue
            if source_ref.quote not in source_content:
                mismatches.append(
                    f"{source_ref.source_id} does not contain {source_ref.quote!r}"
                )

    if mismatches:
        return CheckResult(
            "source_refs.quote 能在对应消息中找到",
            False,
            "; ".join(mismatches),
        )
    return CheckResult("source_refs.quote 能在对应消息中找到", True, "ok")


def _all_records_have_text(records: list[MemoryRecord]) -> CheckResult:
    empty_count = sum(1 for record in records if not record.text.strip())
    if empty_count:
        return CheckResult(
            "所有候选都有非空 text",
            False,
            f"{empty_count} records have empty text",
        )
    return CheckResult("所有候选都有非空 text", True, "ok")


def _time_refs_have_required_metadata(records: list[MemoryRecord]) -> CheckResult:
    failures: list[str] = []
    for record in records:
        if record.memory_type != "time_ref":
            continue
        metadata = record.metadata
        missing_base = _missing_fields(metadata, TIME_REF_BASE_FIELDS)
        if missing_base:
            failures.append(f"time_ref missing base fields {missing_base}")
            continue
        time_kind = str(metadata.get("time_kind"))
        timeline_kind = str(metadata.get("timeline_kind"))
        certainty = str(metadata.get("certainty"))
        if time_kind not in ALLOWED_TIME_KINDS:
            failures.append(f"time_ref has invalid time_kind {time_kind!r}")
        if timeline_kind not in ALLOWED_TIMELINE_KINDS:
            failures.append(f"time_ref has invalid timeline_kind {timeline_kind!r}")
        if certainty not in ALLOWED_CERTAINTY:
            failures.append(f"time_ref has invalid certainty {certainty!r}")
        if time_kind in TIME_KIND_REQUIRED_FIELDS:
            missing_kind = _missing_fields(
                metadata,
                TIME_KIND_REQUIRED_FIELDS[time_kind],
            )
            if missing_kind:
                failures.append(
                    f"time_ref kind={time_kind} missing fields {missing_kind}"
                )

    if failures:
        return CheckResult("time_ref metadata 符合稳定契约", False, "; ".join(failures))
    return CheckResult("time_ref metadata 符合稳定契约", True, "ok")


def _time_links_reference_existing_candidates(
    records: list[MemoryRecord],
) -> CheckResult:
    candidate_ids = {
        record.metadata.get("candidate_client_id")
        for record in records
        if isinstance(record.metadata.get("candidate_client_id"), str)
    }
    failures: list[str] = []
    for record in records:
        if record.memory_type != "time_link":
            continue
        metadata = record.metadata
        target_id = metadata.get("target_client_id")
        time_ref_id = metadata.get("time_ref_client_id")
        time_role = metadata.get("time_role")
        if target_id not in candidate_ids:
            failures.append(f"time_link target {target_id!r} missing")
        if time_ref_id not in candidate_ids:
            failures.append(f"time_link time_ref {time_ref_id!r} missing")
        if time_role not in ALLOWED_TIME_ROLES:
            failures.append(f"time_link time_role {time_role!r} invalid")

    if failures:
        return CheckResult("time_link 引用存在且角色合法", False, "; ".join(failures))
    return CheckResult("time_link 引用存在且角色合法", True, "ok")


def _events_have_time_links(records: list[MemoryRecord]) -> CheckResult:
    linked_target_ids = {
        record.metadata.get("target_client_id")
        for record in records
        if record.memory_type == "time_link"
    }
    failures: list[str] = []
    for record in records:
        if record.memory_type != "event":
            continue
        client_id = record.metadata.get("candidate_client_id")
        if not client_id:
            failures.append(f"event {record.text!r} missing candidate_client_id")
        elif client_id not in linked_target_ids:
            failures.append(f"event {client_id!r} has no time_link")

    if failures:
        return CheckResult("event 都有独立 time_ref/time_link", False, "; ".join(failures))
    return CheckResult("event 都有独立 time_ref/time_link", True, "ok")


def _missing_fields(
    metadata: dict[str, object],
    fields: set[str],
) -> list[str]:
    return [
        field
        for field in fields
        if not isinstance(metadata.get(field), str) or not str(metadata[field]).strip()
    ]
