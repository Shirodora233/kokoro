"""Run real-LLM memory tests against PostgreSQL persistence."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from conversation.config import StorageConfig
from llm.config import LLMConfig
from llm.openai_client import OpenAIChatClient
from memory.config import MemoryRuntimeConfig
from memory.extraction import LLMMemoryExtractor, MemoryExtractionPromptBuilder
from memory.models import MemoryInputMessage, MemoryTurnCommitInput, MemoryTurnResult
from memory.persistence import MemoryWriteResultPersistenceSync
from memory.persistence.postgres import PostgresPersistentMemoryRepository
from memory.retrieval import (
    NormalizedMemoryContextRetriever,
    PostgresNormalizedMemorySearch,
)
from memory.storage.postgres import PostgresMemoryStore
from memory.system import InMemoryMemorySystem
from tests.memory.system_real.recording import RecordingChatClient, TokenUsage

USER_ID_PREFIX = "usr_pg_real_memory"
SESSION_ID_PREFIX = "ses_pg_real_memory"


@dataclass(frozen=True)
class CheckResult:
    label: str
    passed: bool
    detail: str


@dataclass
class TurnCapture:
    label: str
    user_message: MemoryInputMessage
    result: MemoryTurnResult | None = None
    error: str | None = None
    duration_seconds: float | None = None
    token_usage: TokenUsage | None = None
    llm_input: list[dict[str, str]] = field(default_factory=list)
    llm_output: str | None = None


@dataclass
class ScenarioCapture:
    user_id: str
    session_id: str
    turns: list[TurnCapture]
    generic_records: list[dict[str, Any]]
    normalized_rows: dict[str, list[dict[str, Any]]]
    duplicate_links: list[dict[str, Any]]
    duplicate_time_links: list[dict[str, Any]]
    checks: list[CheckResult]

    @property
    def passed(self) -> bool:
        return all(turn.error is None for turn in self.turns) and all(
            check.passed for check in self.checks
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run real LLM PostgreSQL memory persistence tests"
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
        help="Keep generated PostgreSQL test rows for manual inspection.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    env_file = Path(args.env_file)
    storage_config = StorageConfig.from_env(env_file)
    if not storage_config.database_url:
        raise SystemExit("CONVERSATION_DATABASE_URL or DATABASE_URL is required")

    llm_config = LLMConfig.from_env(env_file)
    memory_config = MemoryRuntimeConfig.from_env(env_file)
    chat_client = RecordingChatClient(OpenAIChatClient(llm_config))
    suffix = datetime.now(UTC).strftime("%Y%m%d%H%M%S") + "_" + uuid4().hex[:8]
    user_id = f"{USER_ID_PREFIX}_{suffix}"
    session_id = f"{SESSION_ID_PREFIX}_{suffix}"

    capture: ScenarioCapture | None = None
    try:
        capture = _run_scenario(
            database_url=storage_config.database_url,
            llm_config=llm_config,
            memory_config=memory_config,
            chat_client=chat_client,
            user_id=user_id,
            session_id=session_id,
        )
        report_path = (
            Path(args.report_path) if args.report_path else _default_report_path()
        )
        _write_report(
            report_path,
            capture=capture,
            model=llm_config.model,
            extraction_model=memory_config.extraction_model,
            base_url_configured=bool(llm_config.base_url),
        )
        print(f"report={report_path}")
        print(f"passed={1 if capture.passed else 0}/1")
        return 1 if args.strict and not capture.passed else 0
    finally:
        if not args.keep_data:
            _cleanup(storage_config.database_url, user_id=user_id, session_id=session_id)


def _run_scenario(
    *,
    database_url: str,
    llm_config: LLMConfig,
    memory_config: MemoryRuntimeConfig,
    chat_client: RecordingChatClient,
    user_id: str,
    session_id: str,
) -> ScenarioCapture:
    store = PostgresMemoryStore(database_url)
    repository = PostgresPersistentMemoryRepository(database_url)
    system = InMemoryMemorySystem(
        store=store,
        extractor=LLMMemoryExtractor(
            chat_client=chat_client,
            model=memory_config.extraction_model or llm_config.model,
            temperature=memory_config.extraction_temperature,
            prompt_builder=MemoryExtractionPromptBuilder(
                max_context_messages=memory_config.extraction_max_context_messages,
            ),
        ),
        context_retriever=NormalizedMemoryContextRetriever(
            repository,
            search=PostgresNormalizedMemorySearch(repository),
        ),
        persistence_sync=MemoryWriteResultPersistenceSync(repository),
    )

    messages = [
        MemoryInputMessage(
            id=f"msg_{session_id}_spicy_pref",
            role="user",
            content="我不喜欢吃辣，推荐一些美食。",
            user_id=user_id,
            session_id=session_id,
            created_at="2026-05-31T19:00:00+08:00",
        ),
        MemoryInputMessage(
            id=f"msg_{session_id}_pad_krapow",
            role="user",
            content="想起来前几天去吃打抛饭，但是那个吃起来很辣。",
            user_id=user_id,
            session_id=session_id,
            created_at="2026-05-31T19:05:00+08:00",
        ),
    ]

    turns: list[TurnCapture] = []
    conversation_context: list[MemoryInputMessage] = []
    for index, message in enumerate(messages, start=1):
        conversation_context.append(message)
        turn_capture = TurnCapture(label=f"turn_{index}", user_message=message)
        chat_client.clear()
        start = time.perf_counter()
        try:
            prepare = system.prepare_turn(
                _memory_turn(
                    user_id=user_id,
                    session_id=session_id,
                    new_message=message,
                    conversation_context=conversation_context,
                )
            )
            turn_capture.result = system.commit_turn(
                MemoryTurnCommitInput(
                    snapshot=prepare.snapshot,
                    assistant_message=MemoryInputMessage(
                        id=f"{message.id}_assistant",
                        role="assistant",
                        content="",
                        session_id=session_id,
                    ),
                )
            )
        except Exception as error:
            turn_capture.error = f"{type(error).__name__}: {error}"
        finally:
            turn_capture.duration_seconds = time.perf_counter() - start
            turn_capture.token_usage = chat_client.last_usage
            turn_capture.llm_input = chat_client.last_input
            turn_capture.llm_output = chat_client.last_output
            turns.append(turn_capture)
        if turn_capture.error:
            break

    generic_records = [
        record.to_record()
        for record in store.list_records(user_id=user_id, session_id=session_id)
    ]
    normalized_rows = _load_normalized_rows(repository, user_id, session_id)
    duplicate_links = _duplicate_links(repository, user_id, session_id)
    duplicate_time_links = _duplicate_time_links(repository, session_id)
    checks = _checks(
        turns=turns,
        generic_records=generic_records,
        normalized_rows=normalized_rows,
        duplicate_links=duplicate_links,
        duplicate_time_links=duplicate_time_links,
    )
    return ScenarioCapture(
        user_id=user_id,
        session_id=session_id,
        turns=turns,
        generic_records=generic_records,
        normalized_rows=normalized_rows,
        duplicate_links=duplicate_links,
        duplicate_time_links=duplicate_time_links,
        checks=checks,
    )


def _memory_turn(
    *,
    user_id: str,
    session_id: str,
    new_message: MemoryInputMessage,
    conversation_context: list[MemoryInputMessage],
):
    from memory.models import ConversationContextState, MemoryTurnInput

    return MemoryTurnInput(
        user_id=user_id,
        session_id=session_id,
        new_message=new_message,
        timezone="Asia/Shanghai",
        conversation_context=list(conversation_context),
        context_state=ConversationContextState(
            context_start_index=0,
            total_messages=len(conversation_context),
            max_context_messages=20,
            active_message_ids=[message.id for message in conversation_context],
        ),
    )


def _checks(
    *,
    turns: list[TurnCapture],
    generic_records: list[dict[str, Any]],
    normalized_rows: dict[str, list[dict[str, Any]]],
    duplicate_links: list[dict[str, Any]],
    duplicate_time_links: list[dict[str, Any]],
) -> list[CheckResult]:
    return [
        _check_no_turn_errors(turns),
        _check_no_persistent_sync_errors(turns),
        _check_generic_records(generic_records),
        _check_normalized_event(normalized_rows),
        _check_normalized_food_property(normalized_rows),
        _check_no_duplicate_links(duplicate_links),
        _check_no_duplicate_time_links(duplicate_time_links),
    ]


def _check_no_turn_errors(turns: list[TurnCapture]) -> CheckResult:
    errors = [turn.error for turn in turns if turn.error]
    if errors:
        return CheckResult("真实 LLM turn 不抛异常", False, "; ".join(errors))
    return CheckResult("真实 LLM turn 不抛异常", True, "ok")


def _check_no_persistent_sync_errors(turns: list[TurnCapture]) -> CheckResult:
    errors: list[str] = []
    for turn in turns:
        if turn.result is None:
            continue
        persistent_write = turn.result.metadata.get("persistent_write")
        if isinstance(persistent_write, dict) and persistent_write.get("error"):
            errors.append(str(persistent_write["error"]))
    if errors:
        return CheckResult("PostgreSQL normalized sync 不失败", False, "; ".join(errors))
    return CheckResult("PostgreSQL normalized sync 不失败", True, "ok")


def _check_generic_records(records: list[dict[str, Any]]) -> CheckResult:
    text = _searchable_records(records)
    missing = [needle for needle in ("打抛饭", "辣") if needle not in text]
    if missing:
        return CheckResult(
            "generic memory records 包含打抛饭和辣",
            False,
            f"missing {missing}",
        )
    return CheckResult("generic memory records 包含打抛饭和辣", True, "ok")


def _check_normalized_event(rows: dict[str, list[dict[str, Any]]]) -> CheckResult:
    text = _searchable_records([*rows["events"], *rows["descriptions"]])
    if "打抛饭" not in text:
        return CheckResult("normalized event/description 记录打抛饭经历", False, text)
    return CheckResult("normalized event/description 记录打抛饭经历", True, "ok")


def _check_normalized_food_property(
    rows: dict[str, list[dict[str, Any]]],
) -> CheckResult:
    text = _searchable_records([*rows["entities"], *rows["properties"]])
    missing = [needle for needle in ("打抛饭", "辣") if needle not in text]
    if missing:
        return CheckResult(
            "normalized entity/property 记录打抛饭很辣",
            False,
            f"missing {missing}",
        )
    return CheckResult("normalized entity/property 记录打抛饭很辣", True, "ok")


def _check_no_duplicate_links(duplicates: list[dict[str, Any]]) -> CheckResult:
    if duplicates:
        return CheckResult("memory_links 无重复自然关系", False, json.dumps(duplicates))
    return CheckResult("memory_links 无重复自然关系", True, "ok")


def _check_no_duplicate_time_links(duplicates: list[dict[str, Any]]) -> CheckResult:
    if duplicates:
        return CheckResult(
            "memory_time_links 无重复自然关系",
            False,
            json.dumps(duplicates),
        )
    return CheckResult("memory_time_links 无重复自然关系", True, "ok")


def _load_normalized_rows(
    repository: PostgresPersistentMemoryRepository,
    user_id: str,
    session_id: str,
) -> dict[str, list[dict[str, Any]]]:
    with repository.database.connect() as connection:
        return {
            "events": _rows(
                connection,
                "SELECT id, title, summary, event_type, metadata FROM memory_events "
                "WHERE user_id = %s AND session_id = %s ORDER BY created_at",
                (user_id, session_id),
            ),
            "descriptions": _rows(
                connection,
                "SELECT id, event_id, content, description_type, metadata "
                "FROM memory_descriptions "
                "WHERE user_id = %s AND session_id = %s ORDER BY created_at",
                (user_id, session_id),
            ),
            "entities": _rows(
                connection,
                "SELECT id, name, entity_type, identity_summary, metadata "
                "FROM memory_entities "
                "WHERE user_id = %s AND session_id = %s ORDER BY created_at",
                (user_id, session_id),
            ),
            "properties": _rows(
                connection,
                "SELECT id, entity_id, content, property_type, metadata "
                "FROM memory_properties "
                "WHERE user_id = %s AND session_id = %s ORDER BY created_at",
                (user_id, session_id),
            ),
            "links": _rows(
                connection,
                "SELECT id, from_type, from_id, to_type, to_id, relation_type, "
                "metadata FROM memory_links "
                "WHERE user_id = %s OR metadata->>'session_id' = %s "
                "ORDER BY created_at",
                (user_id, session_id),
            ),
            "time_refs": _rows(
                connection,
                "SELECT id, raw_text, time_kind, timeline_kind, certainty, metadata "
                "FROM memory_time_refs "
                "WHERE metadata->>'session_id' = %s ORDER BY created_at",
                (session_id,),
            ),
            "time_links": _rows(
                connection,
                "SELECT id, target_type, target_id, time_ref_id, time_role, metadata "
                "FROM memory_time_links "
                "WHERE metadata->>'session_id' = %s ORDER BY created_at",
                (session_id,),
            ),
        }


def _duplicate_links(
    repository: PostgresPersistentMemoryRepository,
    user_id: str,
    session_id: str,
) -> list[dict[str, Any]]:
    with repository.database.connect() as connection:
        return _rows(
            connection,
            """
            SELECT from_type, from_id, to_type, to_id, relation_type, count(*) AS count
            FROM memory_links
            WHERE user_id = %s OR metadata->>'session_id' = %s
            GROUP BY from_type, from_id, to_type, to_id, relation_type
            HAVING count(*) > 1
            ORDER BY count DESC
            """,
            (user_id, session_id),
        )


def _duplicate_time_links(
    repository: PostgresPersistentMemoryRepository,
    session_id: str,
) -> list[dict[str, Any]]:
    with repository.database.connect() as connection:
        return _rows(
            connection,
            """
            SELECT target_type, target_id, time_ref_id, time_role, count(*) AS count
            FROM memory_time_links
            WHERE metadata->>'session_id' = %s
            GROUP BY target_type, target_id, time_ref_id, time_role
            HAVING count(*) > 1
            ORDER BY count DESC
            """,
            (session_id,),
        )


def _rows(connection, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _searchable_records(records: list[dict[str, Any]]) -> str:
    return json.dumps(records, ensure_ascii=False)


def _write_report(
    path: Path,
    *,
    capture: ScenarioCapture,
    model: str,
    extraction_model: str | None,
    base_url_configured: bool,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    status = "PASS" if capture.passed else "FAIL"
    usage = _sum_usage(capture.turns)
    lines = [
        "# PostgreSQL Memory Real LLM Report",
        "",
        f"- Generated at: {datetime.now(UTC).isoformat()}",
        f"- Overall: {status}",
        f"- User id: `{capture.user_id}`",
        f"- Session id: `{capture.session_id}`",
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
        "This test uses the real `LLMMemoryExtractor`, `PostgresMemoryStore`, "
        "`MemoryWriteResultPersistenceSync`, and normalized PostgreSQL memory "
        "tables. It targets the duplicate entity/property/link pattern observed "
        "around `吃打抛饭经历`.",
        "",
        "## Checks",
        "",
    ]
    for check in capture.checks:
        mark = "PASS" if check.passed else "FAIL"
        lines.append(f"- {mark}: {check.label} - {check.detail}")
    lines.extend(["", "## Turns", ""])
    for turn in capture.turns:
        lines.extend(_turn_report(turn))
    lines.extend(_json_section("Generic Records", capture.generic_records))
    lines.extend(_json_section("Normalized Rows", capture.normalized_rows))
    lines.extend(_json_section("Duplicate Links", capture.duplicate_links))
    lines.extend(_json_section("Duplicate Time Links", capture.duplicate_time_links))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _turn_report(turn: TurnCapture) -> list[str]:
    status = "PASS" if turn.error is None else "FAIL"
    lines = [
        f"### {turn.label}: {status}",
        "",
        "#### User Message",
        "",
        "```text",
        turn.user_message.content,
        "```",
        "",
        f"- Duration: `{turn.duration_seconds:.2f}s`"
        if turn.duration_seconds is not None
        else "- Duration: `n/a`",
        f"- Input tokens: `{_format_token(turn.token_usage.input_tokens if turn.token_usage else None)}`",
        f"- Output tokens: `{_format_token(turn.token_usage.output_tokens if turn.token_usage else None)}`",
        f"- Total tokens: `{_format_token(turn.token_usage.total_tokens if turn.token_usage else None)}`",
        f"- Cached input tokens: `{_format_token(turn.token_usage.cached_tokens if turn.token_usage else None)}`",
        "",
    ]
    if turn.error:
        lines.extend(["#### Error", "", "```text", turn.error, "```", ""])
    lines.extend(_json_details("Raw LLM input messages", turn.llm_input))
    lines.extend(_text_details("Raw LLM output", turn.llm_output or "<no output>"))
    if turn.result is not None:
        lines.extend(_json_details("MemoryTurnResult", turn.result.to_record()))
    return lines


def _json_section(title: str, payload: Any) -> list[str]:
    return [
        f"## {title}",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
    ]


def _json_details(summary: str, payload: Any) -> list[str]:
    return [
        "<details>",
        f"<summary>{summary}</summary>",
        "",
        "```json",
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "</details>",
        "",
    ]


def _text_details(summary: str, text: str) -> list[str]:
    return [
        "<details>",
        f"<summary>{summary}</summary>",
        "",
        "```text",
        text,
        "```",
        "",
        "</details>",
        "",
    ]


def _sum_usage(turns: list[TurnCapture]) -> TokenUsage:
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    cached_tokens = 0
    saw_input = False
    saw_output = False
    saw_total = False
    saw_cached = False
    for turn in turns:
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


def _default_report_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Path("tests") / "memory" / "postgres_real" / "reports" / f"{timestamp}.md"


def _cleanup(database_url: str, *, user_id: str, session_id: str) -> None:
    repository = PostgresPersistentMemoryRepository(database_url)
    with repository.database.connect() as connection:
        ids = {
            "record": [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM memory_records WHERE session_id = %s",
                    (session_id,),
                ).fetchall()
            ],
            "event": _ids_for_session(connection, "memory_events", session_id),
            "description": _ids_for_session(
                connection,
                "memory_descriptions",
                session_id,
            ),
            "entity": _ids_for_session(connection, "memory_entities", session_id),
            "property": _ids_for_session(connection, "memory_properties", session_id),
            "link": [
                row["id"]
                for row in connection.execute(
                    """
                    SELECT id FROM memory_links
                    WHERE user_id = %s OR metadata->>'session_id' = %s
                    """,
                    (user_id, session_id),
                ).fetchall()
            ],
            "time_ref": [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM memory_time_refs WHERE metadata->>'session_id' = %s",
                    (session_id,),
                ).fetchall()
            ],
            "time_link": [
                row["id"]
                for row in connection.execute(
                    "SELECT id FROM memory_time_links WHERE metadata->>'session_id' = %s",
                    (session_id,),
                ).fetchall()
            ],
        }
        for memory_type, object_ids in ids.items():
            if memory_type == "record" or not object_ids:
                continue
            connection.execute(
                "DELETE FROM memory_sources WHERE memory_type = %s AND memory_id = ANY(%s)",
                (memory_type, object_ids),
            )
        if ids["record"]:
            connection.execute(
                "DELETE FROM memory_source_refs WHERE memory_record_id = ANY(%s)",
                (ids["record"],),
            )
        _delete_ids(connection, "memory_time_links", ids["time_link"])
        _delete_ids(connection, "memory_links", ids["link"])
        _delete_ids(connection, "memory_properties", ids["property"])
        _delete_ids(connection, "memory_descriptions", ids["description"])
        _delete_ids(connection, "memory_time_refs", ids["time_ref"])
        _delete_ids(connection, "memory_entities", ids["entity"])
        _delete_ids(connection, "memory_events", ids["event"])
        _delete_ids(connection, "memory_records", ids["record"])


def _ids_for_session(connection, table: str, session_id: str) -> list[str]:
    return [
        row["id"]
        for row in connection.execute(
            f"SELECT id FROM {table} WHERE session_id = %s",
            (session_id,),
        ).fetchall()
    ]


def _delete_ids(connection, table: str, ids: list[str]) -> None:
    if ids:
        connection.execute(f"DELETE FROM {table} WHERE id = ANY(%s)", (ids,))


if __name__ == "__main__":
    sys.exit(main())
