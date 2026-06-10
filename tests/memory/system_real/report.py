"""Markdown report generation for real memory-system integration tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .checks import ScenarioResult, TurnRun
from .recording import TokenUsage


def write_report(
    path: Path,
    results: list[ScenarioResult],
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
    results: list[ScenarioResult],
    model: str,
    extraction_model: str | None,
    base_url_configured: bool,
) -> str:
    passed_count = sum(1 for result in results if result.passed)
    status = "PASS" if passed_count == len(results) else "FAIL"
    usage = _sum_usage(results)
    lines = [
        "# Memory System Real Test Report",
        "",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        f"- Overall: {status}",
        f"- Passed scenarios: {passed_count}/{len(results)}",
        f"- Chat model: `{model}`",
        f"- Extraction model: `{extraction_model or model}`",
        f"- Base URL configured: `{base_url_configured}`",
        f"- Total input tokens: `{_format_token(usage.input_tokens)}`",
        f"- Total output tokens: `{_format_token(usage.output_tokens)}`",
        f"- Total tokens: `{_format_token(usage.total_tokens)}`",
        f"- Cached input tokens: `{_format_token(usage.cached_tokens)}`",
        "",
        "## Scope",
        "",
        "This report tests the real `LLMMemoryExtractor` wired through "
        "`MemoryRuntime`: prompt construction, real LLM extraction, "
        "candidate retrieval, deterministic reconciliation, write-plan "
        "application, active-memory refresh, and prompt-context retrieval. It "
        "still uses an in-memory store rather than PostgreSQL memory tables.",
        "",
    ]
    for result in results:
        lines.extend(_scenario_section(result))
    return "\n".join(lines) + "\n"


def _scenario_section(result: ScenarioResult) -> list[str]:
    status = "PASS" if result.passed else "FAIL"
    lines = [
        f"## {result.scenario.scenario_id}: {status}",
        "",
        f"**Title:** {result.scenario.title}",
        "",
        f"**Description:** {result.scenario.description}",
        "",
        "### Checks",
        "",
    ]
    for check in result.checks:
        mark = "PASS" if check.passed else "FAIL"
        lines.append(f"- {mark}: {check.label} - {check.detail}")
    lines.append("")
    lines.extend(_source_messages_section(result))
    lines.extend(_turn_sections(result.turns))
    lines.extend(_final_records_section(result))
    lines.extend(_active_context_section(result))
    return lines


def _source_messages_section(result: ScenarioResult) -> list[str]:
    lines = ["### Source Messages", ""]
    for index, turn in enumerate(result.scenario.turns, start=1):
        lines.extend([f"#### Turn {index}", ""])
        for message in turn.conversation_context:
            lines.extend(
                [
                    f"##### {message.id} `{message.role}`",
                    "",
                    "```text",
                    message.content,
                    "```",
                    "",
                ]
            )
    return lines


def _turn_sections(turns: list[TurnRun]) -> list[str]:
    lines = ["### Turn Runs", ""]
    for turn in turns:
        status = "PASS" if turn.passed else "FAIL"
        lines.extend(
            [
                f"#### Turn {turn.turn_index}: {status}",
                "",
                f"**Duration:** {_format_duration(turn.duration_seconds)}",
                "",
            ]
        )
        lines.extend(_token_usage_section(turn.token_usage))
        lines.extend(_raw_llm_exchange_section(turn))
        if turn.error:
            lines.extend(["**Error:**", "", f"```text\n{turn.error}\n```", ""])
            continue
        if turn.result is not None:
            lines.extend(
                [
                    "<details>",
                    "<summary>MemoryTurnResult</summary>",
                    "",
                    "```json",
                    json.dumps(turn.result.to_record(), ensure_ascii=False, indent=2),
                    "```",
                    "",
                    "</details>",
                    "",
                ]
            )
    return lines


def _final_records_section(result: ScenarioResult) -> list[str]:
    lines = ["### Final Store Records", ""]
    if not result.final_records:
        return [*lines, "No records.", ""]
    for index, record in enumerate(result.final_records, start=1):
        lines.extend(
            [
                f"#### Record {index}: `{record.memory_type}`",
                "",
                "```json",
                json.dumps(record.to_record(), ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    return lines


def _active_context_section(result: ScenarioResult) -> list[str]:
    lines = [
        "### Final Active Context",
        "",
        "```json",
        json.dumps(result.active_context, ensure_ascii=False, indent=2),
        "```",
        "",
    ]
    return lines


def _token_usage_section(usage: TokenUsage | None) -> list[str]:
    if usage is None:
        return ["**Token Usage:** n/a", ""]
    lines = [
        "##### Token Usage",
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


def _raw_llm_exchange_section(turn: TurnRun) -> list[str]:
    lines = [
        "<details>",
        "<summary>Raw LLM input messages</summary>",
        "",
        "```json",
        json.dumps(turn.llm_input, ensure_ascii=False, indent=2),
        "```",
        "",
        "</details>",
        "",
        "<details>",
        "<summary>Raw LLM output</summary>",
        "",
    ]
    if turn.llm_output is None:
        lines.extend(["```text", "<no output>", "```", ""])
    else:
        lines.extend(["```json", turn.llm_output, "```", ""])
    lines.extend(["</details>", ""])
    return lines


def _sum_usage(results: list[ScenarioResult]) -> TokenUsage:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cached_tokens = 0
    saw_input = False
    saw_output = False
    saw_total = False
    saw_cached = False
    for result in results:
        for turn in result.turns:
            usage = turn.token_usage
            if usage is None:
                continue
            if usage.input_tokens is not None:
                saw_input = True
                input_tokens += usage.input_tokens
            if usage.output_tokens is not None:
                saw_output = True
                output_tokens += usage.output_tokens
            if usage.total_tokens is not None:
                saw_total = True
                total_tokens += usage.total_tokens
            if usage.cached_tokens is not None:
                saw_cached = True
                cached_tokens += usage.cached_tokens
    return TokenUsage(
        input_tokens=input_tokens if saw_input else None,
        output_tokens=output_tokens if saw_output else None,
        total_tokens=total_tokens if saw_total else None,
        cached_tokens=cached_tokens if saw_cached else None,
    )


def _format_token(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _format_duration(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}s"
