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


DEFAULT_FRESH_MESSAGES = [
    "请记住：我喜欢茉莉花茶少糖。",
    "再确认一下，请记住：我喜欢茉莉花茶少糖。",
]
DEFAULT_RESUME_MESSAGE = "继续这个存档点测试：请记住，我周五要带雨伞。"
CHECKPOINT_LIST_LIMIT = 10_000
DEBUG_LIST_LIMIT = 1_000


@dataclass(frozen=True)
class ResumeConfig:
    session_id: str
    base_checkpoint_id: str | None
    message: str
    branch_title: str | None = None


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
    mode: str = "fresh"
    user_id: str | None = None
    session_id: str | None = None
    source_session_id: str | None = None
    base_checkpoint_id: str | None = None
    branch_session_id: str | None = None
    resume_message: str | None = None
    baseline_checkpoint_ids: list[str] = field(default_factory=list)
    new_checkpoint_ids: list[str] = field(default_factory=list)
    baseline_debug_trace_ids: list[str] = field(default_factory=list)
    new_debug_trace_ids: list[str] = field(default_factory=list)
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
    parser.add_argument(
        "--resume-session-id",
        default=None,
        help=(
            "Continue an existing session instead of creating a fresh fixture. "
            "When --base-checkpoint-id is also set, the runner first creates a "
            "branch from that checkpoint."
        ),
    )
    parser.add_argument(
        "--base-checkpoint-id",
        default=None,
        help=(
            "Checkpoint to resume from. Use with --resume-session-id. "
            "The value 'latest' resolves to the latest visible checkpoint."
        ),
    )
    parser.add_argument(
        "--resume-message",
        default=DEFAULT_RESUME_MESSAGE,
        help="User message sent after resolving the resume target.",
    )
    parser.add_argument(
        "--branch-title",
        default=None,
        help="Optional title for the branch created by --base-checkpoint-id.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.base_checkpoint_id and not args.resume_session_id:
        parser.error("--base-checkpoint-id requires --resume-session-id")

    resume = (
        ResumeConfig(
            session_id=args.resume_session_id,
            base_checkpoint_id=args.base_checkpoint_id,
            message=args.resume_message,
            branch_title=args.branch_title,
        )
        if args.resume_session_id
        else None
    )
    env_file = Path(args.env_file)
    storage_config = StorageConfig.from_env(env_file)
    if not storage_config.database_url:
        raise SystemExit("CONVERSATION_DATABASE_URL or DATABASE_URL is required")

    username = (
        "resume_existing_session"
        if resume is not None
        else "llm_reconciliation_real_"
        + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        + "_"
        + uuid4().hex[:8]
    )
    capture = ConversationLLMReconciliationCapture(
        username=username,
        mode="resume" if resume is not None else "fresh",
        source_session_id=resume.session_id if resume is not None else None,
        base_checkpoint_id=resume.base_checkpoint_id if resume is not None else None,
        resume_message=resume.message if resume is not None else None,
    )
    try:
        capture = _run_case(env_file=env_file, username=username, resume=resume)
    except Exception as error:
        capture.error = str(error)
    finally:
        if not args.keep_data and resume is None:
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
    resume: ResumeConfig | None = None,
) -> ConversationLLMReconciliationCapture:
    service = ConversationService.default(env_file)
    recorder = _wrap_service_chat_client(service)
    capture = ConversationLLMReconciliationCapture(
        username=username,
        mode="resume" if resume is not None else "fresh",
    )

    if resume is None:
        _run_fresh_case(service, capture, username)
    else:
        _run_resume_case(service, capture, resume)

    if capture.session_id is None:
        raise RuntimeError("test case did not resolve a session_id")
    _capture_session_state(service, capture, capture.session_id)
    capture.llm_calls = list(recorder.calls)
    capture.checks = _build_checks(service, capture)
    return capture


def _run_fresh_case(
    service: ConversationService,
    capture: ConversationLLMReconciliationCapture,
    username: str,
) -> None:
    user = service.create_user(username=username, display_name="LLM Reconciliation")
    session = service.start_session(
        user.id,
        title="LLM reconciliation real test",
        system_prompt="你是一个简短回答助手。请用一句话回应用户。",
        temperature=0.0,
    )
    capture.user_id = user.id
    capture.session_id = session.id
    capture.source_session_id = session.id
    capture.baseline_checkpoint_ids = []
    capture.baseline_debug_trace_ids = []

    for message in DEFAULT_FRESH_MESSAGES:
        service.send_message(session.id, message)


def _run_resume_case(
    service: ConversationService,
    capture: ConversationLLMReconciliationCapture,
    resume: ResumeConfig,
) -> None:
    source_session = service.store.get_session(resume.session_id)
    if source_session is None:
        raise ValueError(f"Unknown resume session_id: {resume.session_id}")
    user = service.store.get_user(source_session.user_id)
    if user is None:
        raise ValueError(f"Unknown user_id for resume session: {source_session.user_id}")

    capture.username = user.username
    capture.user_id = user.id
    capture.source_session_id = source_session.id
    capture.session_id = source_session.id
    capture.resume_message = resume.message

    target_session_id = source_session.id
    if resume.base_checkpoint_id:
        checkpoint_id = _resolve_base_checkpoint_id(
            service,
            source_session.id,
            resume.base_checkpoint_id,
        )
        branch = service.create_branch_from_checkpoint(
            source_session.id,
            checkpoint_id,
            title=resume.branch_title or _default_branch_title(checkpoint_id),
        )
        capture.base_checkpoint_id = checkpoint_id
        capture.branch_session_id = branch.id
        capture.session_id = branch.id
        target_session_id = branch.id
    else:
        capture.base_checkpoint_id = None

    _record_baseline(service, capture, target_session_id)
    service.send_message(
        target_session_id,
        resume.message,
        metadata={
            "test_mode": "llm_reconciliation_resume",
            "source_session_id": source_session.id,
            "base_checkpoint_id": capture.base_checkpoint_id,
        },
    )


def _resolve_base_checkpoint_id(
    service: ConversationService,
    session_id: str,
    checkpoint_id: str,
) -> str:
    visible = service.list_checkpoints(session_id, limit=CHECKPOINT_LIST_LIMIT)
    if checkpoint_id == "latest":
        if not visible:
            raise ValueError(f"Session has no visible checkpoints: {session_id}")
        return visible[-1].id
    visible_ids = {checkpoint.id for checkpoint in visible}
    if checkpoint_id not in visible_ids:
        raise ValueError(
            f"checkpoint_id is not visible from session_id: {checkpoint_id}"
        )
    return checkpoint_id


def _default_branch_title(checkpoint_id: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"LLM reconciliation resume {timestamp} {checkpoint_id[-8:]}"


def _record_baseline(
    service: ConversationService,
    capture: ConversationLLMReconciliationCapture,
    session_id: str,
) -> None:
    capture.baseline_checkpoint_ids = [
        checkpoint.id
        for checkpoint in service.list_checkpoints(
            session_id,
            limit=CHECKPOINT_LIST_LIMIT,
        )
    ]
    capture.baseline_debug_trace_ids = _trace_ids(
        service.list_session_turn_debug(session_id, limit=DEBUG_LIST_LIMIT)
    )


def _capture_session_state(
    service: ConversationService,
    capture: ConversationLLMReconciliationCapture,
    session_id: str,
) -> None:
    capture.messages = [
        message.to_record() for message in service.get_transcript(session_id)
    ]
    capture.checkpoints = [
        checkpoint.to_record()
        for checkpoint in service.list_checkpoints(
            session_id,
            limit=CHECKPOINT_LIST_LIMIT,
        )
    ]
    capture.debug_summaries = service.list_session_turn_debug(
        session_id,
        limit=DEBUG_LIST_LIMIT,
    )
    checkpoint_ids = [
        checkpoint["id"]
        for checkpoint in capture.checkpoints
        if isinstance(checkpoint.get("id"), str)
    ]
    trace_ids = _trace_ids(capture.debug_summaries)
    capture.new_checkpoint_ids = [
        checkpoint_id
        for checkpoint_id in checkpoint_ids
        if checkpoint_id not in set(capture.baseline_checkpoint_ids)
    ]
    capture.new_debug_trace_ids = [
        trace_id
        for trace_id in trace_ids
        if trace_id not in set(capture.baseline_debug_trace_ids)
    ]
    report_trace_ids = capture.new_debug_trace_ids or trace_ids
    capture.debug_traces = [
        service.get_memory_debug_trace(trace_id, include_raw=False)
        for trace_id in report_trace_ids
    ]
    if capture.checkpoints:
        capture.checkpoint_memory = service.get_checkpoint_memory(
            capture.checkpoints[-1]["id"]
        )


def _trace_ids(summaries: list[dict[str, Any]]) -> list[str]:
    return [
        trace_id
        for summary in summaries
        if isinstance((trace_id := summary.get("trace_id")), str)
    ]


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
    extraction_calls = [
        call for call in capture.llm_calls if call.purpose == "extraction"
    ]
    conversation_calls = [
        call for call in capture.llm_calls if call.purpose == "conversation"
    ]
    expected_turns = 1 if capture.mode == "resume" else len(DEFAULT_FRESH_MESSAGES)
    new_trace_ids = set(capture.new_debug_trace_ids)
    new_committed_summaries = [
        summary
        for summary in capture.debug_summaries
        if summary.get("trace_id") in new_trace_ids
        and summary.get("memory_status") == "committed"
    ]
    new_summary_reconcilers = {
        summary.get("reconciler")
        for summary in capture.debug_summaries
        if summary.get("trace_id") in new_trace_ids and summary.get("reconciler")
    }
    records = _checkpoint_memory_records(capture.checkpoint_memory)
    checks = [
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
            "expected checkpointed turns committed",
            len(capture.new_checkpoint_ids) == expected_turns
            and len(new_committed_summaries) == expected_turns,
            (
                f"mode={capture.mode}, expected={expected_turns}, "
                f"new_checkpoints={len(capture.new_checkpoint_ids)}, "
                f"new_committed_debug_summaries={len(new_committed_summaries)}"
            ),
        ),
        CheckResult(
            "new persisted debug summary marks llm reconciler",
            new_summary_reconcilers == {"llm"},
            f"reconcilers={sorted(str(item) for item in new_summary_reconcilers)}",
        ),
        CheckResult(
            "checkpoint memory has stored records",
            bool(records),
            f"visible_record_count={len(records)}",
        ),
    ]
    if capture.mode == "resume":
        checks.append(
            CheckResult(
                "resume mode targeted existing session",
                bool(capture.source_session_id and capture.user_id),
                (
                    f"source_session_id={capture.source_session_id}, "
                    f"user_id={capture.user_id}"
                ),
            )
        )
        if capture.base_checkpoint_id:
            checks.append(
                CheckResult(
                    "checkpoint resume created branch session",
                    bool(
                        capture.branch_session_id
                        and capture.branch_session_id == capture.session_id
                        and capture.branch_session_id != capture.source_session_id
                    ),
                    (
                        f"base_checkpoint_id={capture.base_checkpoint_id}, "
                        f"branch_session_id={capture.branch_session_id}"
                    ),
                )
            )
    return checks


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
    normalized = snapshot.get("normalized_memories")
    if isinstance(normalized, dict):
        for value in normalized.values():
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
        f"- Mode: `{capture.mode}`",
        f"- Username: `{capture.username}`",
        f"- User ID: `{capture.user_id}`",
        f"- Session ID: `{capture.session_id}`",
        f"- Source Session ID: `{capture.source_session_id}`",
        f"- Base Checkpoint ID: `{capture.base_checkpoint_id}`",
        f"- Branch Session ID: `{capture.branch_session_id}`",
        f"- Resume Message: `{capture.resume_message}`",
        f"- New Checkpoint IDs: `{', '.join(capture.new_checkpoint_ids)}`",
        f"- New Debug Trace IDs: `{', '.join(capture.new_debug_trace_ids)}`",
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
