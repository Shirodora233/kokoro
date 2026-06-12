"""Run a real-LLM conversation test for LLM reconciliation wiring."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from conversation.config import StorageConfig
from conversation.service import ConversationService
from conversation.storage.postgres import PostgresConversationStore
from llm.interfaces import ChatClient, ChatCompletionResult, ChatMessageParam
from memory.reconciliation import LLMMemoryReconciler


@dataclass(frozen=True)
class LLMCall:
    purpose: str
    model: str | None
    temperature: float | None
    duration_seconds: float
    usage: dict[str, Any]
    output_preview: str

    def to_record(self) -> dict[str, Any]:
        return {
            "purpose": self.purpose,
            "model": self.model,
            "temperature": self.temperature,
            "duration_seconds": round(self.duration_seconds, 3),
            "usage": dict(self.usage),
            "output_preview": self.output_preview,
        }


@dataclass(frozen=True)
class CheckResult:
    label: str
    passed: bool
    detail: str


@dataclass
class ConversationLLMReconciliationCapture:
    username: str
    user_id: str | None = None
    session_id: str | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    debug_summaries: list[dict[str, Any]] = field(default_factory=list)
    debug_traces: list[dict[str, Any]] = field(default_factory=list)
    checkpoint_memory: dict[str, Any] = field(default_factory=dict)
    llm_calls: list[LLMCall] = field(default_factory=list)
    checks: list[CheckResult] = field(default_factory=list)
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(check.passed for check in self.checks)


class RecordingChatClient:
    """Record all real chat calls while delegating to the configured client."""

    def __init__(self, inner: ChatClient) -> None:
        self.inner = inner
        self.calls: list[LLMCall] = []

    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        purpose = _classify_call(messages)
        start = time.perf_counter()
        completion = self.inner.complete(
            messages=messages,
            model=model,
            temperature=temperature,
        )
        duration = time.perf_counter() - start
        self.calls.append(
            LLMCall(
                purpose=purpose,
                model=completion.model or model,
                temperature=temperature,
                duration_seconds=duration,
                usage=dict(completion.usage),
                output_preview=_preview(completion.content),
            )
        )
        return completion


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a real LLM ConversationService reconciliation wiring test"
    )
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument(
        "--report-path",
        default=None,
        help="Markdown report path. Defaults to a timestamped report.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 when expectations fail.",
    )
    parser.add_argument(
        "--keep-data",
        action="store_true",
        help="Keep generated PostgreSQL rows for manual inspection.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env_file = Path(args.env_file)
    storage_config = StorageConfig.from_env(env_file)
    if not storage_config.database_url:
        raise SystemExit("CONVERSATION_DATABASE_URL or DATABASE_URL is required")

    username = "llm_reconciliation_real_" + datetime.now(UTC).strftime(
        "%Y%m%d%H%M%S"
    ) + "_" + uuid4().hex[:8]
    capture = ConversationLLMReconciliationCapture(username=username)
    try:
        capture = _run_case(env_file=env_file, username=username)
    except Exception as error:
        capture.error = str(error)
    finally:
        if not args.keep_data:
            _cleanup(storage_config.database_url, username=username)

    report_path = Path(args.report_path) if args.report_path else _default_report_path()
    _write_report(report_path, capture)
    print(f"report={report_path}")
    print(f"passed={1 if capture.passed else 0}/1")
    if args.strict and not capture.passed:
        return 1
    return 0


def _run_case(
    *,
    env_file: Path,
    username: str,
) -> ConversationLLMReconciliationCapture:
    service = ConversationService.default(env_file)
    recorder = _wrap_service_chat_client(service)
    capture = ConversationLLMReconciliationCapture(username=username)

    user = service.create_user(username=username, display_name="LLM Reconciliation")
    session = service.start_session(
        user.id,
        title="LLM reconciliation real test",
        system_prompt="你是一个简短回答助手。请用一句话回应用户。",
        temperature=0.0,
    )
    capture.user_id = user.id
    capture.session_id = session.id

    service.send_message(session.id, "请记住：我喜欢茉莉花茶少糖。")
    service.send_message(session.id, "再确认一下，请记住：我喜欢茉莉花茶少糖。")

    capture.messages = [
        message.to_record() for message in service.get_transcript(session.id)
    ]
    capture.checkpoints = [
        checkpoint.to_record() for checkpoint in service.list_checkpoints(session.id)
    ]
    capture.debug_summaries = service.list_session_turn_debug(session.id)
    capture.debug_traces = [
        service.get_memory_debug_trace(summary["trace_id"], include_raw=False)
        for summary in capture.debug_summaries
        if isinstance(summary.get("trace_id"), str)
    ]
    if capture.checkpoints:
        capture.checkpoint_memory = service.get_checkpoint_memory(
            capture.checkpoints[-1]["id"]
        )
    capture.llm_calls = list(recorder.calls)
    capture.checks = _build_checks(service, capture)
    return capture


def _wrap_service_chat_client(service: ConversationService) -> RecordingChatClient:
    recorder = RecordingChatClient(service.chat_client)
    service.chat_client = recorder
    memory_system = service.memory_system
    extractor = getattr(memory_system, "extractor", None)
    llm_client = getattr(extractor, "llm_client", None)
    if llm_client is not None and hasattr(llm_client, "chat_client"):
        llm_client.chat_client = recorder
    reconciler = getattr(memory_system, "reconciler", None)
    client = getattr(reconciler, "client", None)
    if client is not None and hasattr(client, "chat_client"):
        client.chat_client = recorder
    return recorder


def _build_checks(
    service: ConversationService,
    capture: ConversationLLMReconciliationCapture,
) -> list[CheckResult]:
    reconciler = getattr(service.memory_system, "reconciler", None)
    reconciliation_calls = [
        call for call in capture.llm_calls if call.purpose == "reconciliation"
    ]
    extraction_calls = [call for call in capture.llm_calls if call.purpose == "extraction"]
    conversation_calls = [
        call for call in capture.llm_calls if call.purpose == "conversation"
    ]
    committed_summaries = [
        summary
        for summary in capture.debug_summaries
        if summary.get("memory_status") == "committed"
    ]
    summary_reconcilers = {
        summary.get("reconciler")
        for summary in capture.debug_summaries
        if summary.get("reconciler")
    }
    records = _checkpoint_memory_records(capture.checkpoint_memory)
    return [
        CheckResult(
            "conversation runtime uses LLMMemoryReconciler",
            isinstance(reconciler, LLMMemoryReconciler),
            reconciler.__class__.__name__ if reconciler is not None else "None",
        ),
        CheckResult(
            "real extraction LLM was called",
            bool(extraction_calls),
            f"count={len(extraction_calls)}",
        ),
        CheckResult(
            "real reconciliation LLM was called",
            bool(reconciliation_calls),
            f"count={len(reconciliation_calls)}",
        ),
        CheckResult(
            "conversation assistant LLM was called",
            bool(conversation_calls),
            f"count={len(conversation_calls)}",
        ),
        CheckResult(
            "two checkpointed turns committed",
            len(capture.checkpoints) == 2 and len(committed_summaries) == 2,
            (
                f"checkpoints={len(capture.checkpoints)}, "
                f"committed_debug_summaries={len(committed_summaries)}"
            ),
        ),
        CheckResult(
            "persisted debug summary marks llm reconciler",
            summary_reconcilers == {"llm"},
            f"reconcilers={sorted(str(item) for item in summary_reconcilers)}",
        ),
        CheckResult(
            "checkpoint memory has stored records",
            bool(records),
            f"visible_record_count={len(records)}",
        ),
    ]


def _checkpoint_memory_records(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for key in (
        "events",
        "descriptions",
        "entities",
        "properties",
        "time_refs",
        "links",
        "time_links",
    ):
        value = snapshot.get(key)
        if isinstance(value, list):
            records.extend(item for item in value if isinstance(item, dict))
    return records


def _cleanup(database_url: str, username: str) -> None:
    store = PostgresConversationStore(database_url)
    user = store.find_user_by_username(username)
    if user is None:
        return
    with store.database.connect() as connection:
        connection.execute(
            "DELETE FROM memory_objects WHERE user_id = %s",
            (user.id,),
        )
    store.delete_user(user.id, cascade=True)


def _classify_call(messages: list[ChatMessageParam]) -> str:
    joined = "\n".join(str(message.get("content", "")) for message in messages[:2])
    if "memory reconciliation component" in joined:
        return "reconciliation"
    if "memory extraction component" in joined:
        return "extraction"
    return "conversation"


def _preview(text: str, limit: int = 500) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit] + "..."


def _default_report_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("tests/conversation/reports") / f"llm_reconciliation_{timestamp}.md"


def _write_report(
    path: Path,
    capture: ConversationLLMReconciliationCapture,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# Conversation LLM Reconciliation Real Test Report",
        "",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        f"- Username: `{capture.username}`",
        f"- User ID: `{capture.user_id}`",
        f"- Session ID: `{capture.session_id}`",
        f"- Result: {'PASS' if capture.passed else 'FAIL'}",
        "",
        "## Checks",
        "",
    ]
    for check in capture.checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"- {status}: {check.label} ({check.detail})")
    if capture.error:
        lines.extend(["", "## Error", "", "```text", capture.error, "```"])
    lines.extend(
        [
            "",
            "## LLM Calls",
            "",
            "| # | Purpose | Model | Duration | Tokens |",
            "| ---: | --- | --- | ---: | ---: |",
        ]
    )
    for index, call in enumerate(capture.llm_calls, start=1):
        total_tokens = call.usage.get("total_tokens", "-")
        lines.append(
            "| "
            f"{index} | {call.purpose} | `{call.model}` | "
            f"{call.duration_seconds:.2f}s | {total_tokens} |"
        )
    lines.extend(
        [
            "",
            "## Debug Summaries",
            "",
            "```json",
            json.dumps(capture.debug_summaries, ensure_ascii=False, indent=2),
            "```",
            "",
            "## Checkpoint Memory",
            "",
            "```json",
            json.dumps(capture.checkpoint_memory, ensure_ascii=False, indent=2),
            "```",
            "",
            "## LLM Call Details",
            "",
            "```json",
            json.dumps(
                [call.to_record() for call in capture.llm_calls],
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## Debug Traces",
            "",
            "```json",
            json.dumps(capture.debug_traces, ensure_ascii=False, indent=2),
            "```",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
