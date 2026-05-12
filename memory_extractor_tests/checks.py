"""Expectation checks for extractor integration tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from memory.models import MemoryRecord

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
        _all_records_have_text(records),
    ]


def _has_any_type(records: list[MemoryRecord], types: tuple[str, ...]) -> bool:
    return any(record.memory_type in types for record in records)


def _contains_any(records: list[MemoryRecord], needles: tuple[str, ...]) -> bool:
    text = "\n".join(record.text for record in records).casefold()
    return any(needle.casefold() in text for needle in needles)


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
