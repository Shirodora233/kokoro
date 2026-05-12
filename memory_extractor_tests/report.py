"""Markdown report generation for extractor tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .checks import CaseResult


def write_report(
    path: Path,
    results: list[CaseResult],
    model: str,
    extraction_model: str | None,
    base_url_configured: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        build_report(
            results=results,
            model=model,
            extraction_model=extraction_model,
            base_url_configured=base_url_configured,
        ),
        encoding="utf-8",
    )


def build_report(
    results: list[CaseResult],
    model: str,
    extraction_model: str | None,
    base_url_configured: bool,
) -> str:
    passed_count = sum(1 for result in results if result.passed)
    status = "PASS" if passed_count == len(results) else "FAIL"
    lines = [
        "# Memory Extractor Test Report",
        "",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        f"- Overall: {status}",
        f"- Passed cases: {passed_count}/{len(results)}",
        f"- Chat model: `{model}`",
        f"- Extraction model: `{extraction_model or model}`",
        f"- Base URL configured: `{base_url_configured}`",
        "",
        "## Scope",
        "",
        "This report tests only `LLMMemoryExtractor` as a candidate-fact extractor: "
        "prompt construction, real LLM call, JSON parsing, validation, and "
        "normalization into `MemoryRecord`. It does not test memory persistence, "
        "retrieval, dedupe, merge/update, final write decisions, or conflict "
        "resolution.",
        "",
    ]
    for result in results:
        lines.extend(_case_section(result))
    return "\n".join(lines) + "\n"


def _case_section(result: CaseResult) -> list[str]:
    case_status = "PASS" if result.passed else "FAIL"
    lines = [
        f"## {result.case.case_id}: {case_status}",
        "",
        f"**Title:** {result.case.title}",
        "",
        f"**Description:** {result.case.description}",
        "",
        f"**Scope:** {result.case.scope_note}",
        "",
        f"**Duration:** {result.duration_seconds:.2f}s"
        if result.duration_seconds is not None
        else "**Duration:** n/a",
        "",
    ]
    lines.extend(_token_usage_section(result))
    if result.error:
        lines.extend(["**Error:**", "", f"```text\n{result.error}\n```", ""])
        return lines

    lines.extend(["### Checks", ""])
    for check in result.checks:
        mark = "PASS" if check.passed else "FAIL"
        lines.append(f"- {mark}: {check.label} - {check.detail}")
    lines.extend([""])
    lines.extend(_source_messages_section(result))
    lines.extend(["### Extracted Records", ""])
    if not result.records:
        lines.extend(["No records.", ""])
        return lines

    for index, record in enumerate(result.records, start=1):
        lines.extend(
            [
                f"#### Record {index}",
                "",
                "```json",
                json.dumps(record.to_record(), ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return lines


def _token_usage_section(result: CaseResult) -> list[str]:
    usage = result.token_usage
    if usage is None:
        return ["**Token Usage:** n/a", ""]
    lines = [
        "### Token Usage",
        "",
        f"- Input tokens: `{_format_token(usage.input_tokens)}`",
        f"- Output tokens: `{_format_token(usage.output_tokens)}`",
        f"- Total tokens: `{_format_token(usage.total_tokens)}`",
        f"- Cached input tokens: `{_format_token(usage.cached_tokens)}`",
        "",
    ]
    if usage.raw_usage:
        lines.extend(
            [
                "<details>",
                "<summary>Raw usage</summary>",
                "",
                "```json",
                json.dumps(usage.raw_usage, ensure_ascii=False, indent=2),
                "```",
                "",
                "</details>",
                "",
            ]
        )
    return lines


def _format_token(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _source_messages_section(result: CaseResult) -> list[str]:
    lines = ["### Source Messages", ""]
    for message in result.case.turn.conversation_context:
        lines.extend(
            [
                f"#### {message.id} `{message.role}`",
                "",
                "```text",
                message.content,
                "```",
                "",
            ]
        )
    return lines
