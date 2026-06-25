"""Run real-LLM memory tests against PostgreSQL persistence."""

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
from conversation.storage.postgres import PostgresConversationStore
from llm.config import LLMConfig
from llm.openai_client import OpenAIChatClient
from memory.config import MemoryRuntimeConfig
from memory.extraction import LLMMemoryExtractor, MemoryExtractionPromptBuilder
from memory.models import (
    MemoryInputMessage,
    MemoryRecord,
    MemorySourceRef,
    MemoryTurnCommitInput,
    MemoryTurnResult,
)
from memory.persistence import MemoryRecordPersistenceAdapter
from memory.persistence.postgres import PostgresPersistentMemoryRepository
from memory.retrieval import (
    NormalizedMemoryContextRetriever,
    PostgresNormalizedMemorySearch,
)
from memory.system import MemoryRuntime
from memory.writing import PersistentMemoryWritePlanApplier
from psycopg.types.json import Jsonb
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
    checkpoint_revision_probe: dict[str, Any]
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
    repository = PostgresPersistentMemoryRepository(database_url)
    system = MemoryRuntime(
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
        write_applier=PersistentMemoryWritePlanApplier(repository),
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

    generic_records: list[dict[str, Any]] = []
    normalized_rows = _load_normalized_rows(repository, user_id, session_id)
    checkpoint_revision_probe = _run_checkpoint_revision_probe(
        database_url=database_url,
        repository=repository,
        user_id=user_id,
        session_id=f"{session_id}_checkpoint_probe",
    )
    duplicate_links = _duplicate_links(repository, user_id, session_id)
    duplicate_time_links = _duplicate_time_links(repository, session_id)
    checks = _checks(
        turns=turns,
        generic_records=generic_records,
        normalized_rows=normalized_rows,
        checkpoint_revision_probe=checkpoint_revision_probe,
        duplicate_links=duplicate_links,
        duplicate_time_links=duplicate_time_links,
    )
    return ScenarioCapture(
        user_id=user_id,
        session_id=session_id,
        turns=turns,
        generic_records=generic_records,
        normalized_rows=normalized_rows,
        checkpoint_revision_probe=checkpoint_revision_probe,
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
    checkpoint_revision_probe: dict[str, Any],
    duplicate_links: list[dict[str, Any]],
    duplicate_time_links: list[dict[str, Any]],
) -> list[CheckResult]:
    return [
        _check_no_turn_errors(turns),
        _check_no_write_errors(turns),
        _check_event_entity_refs_do_not_carry_properties(turns),
        _check_normalized_event(normalized_rows),
        _check_normalized_food_property(normalized_rows),
        _check_checkpoint_revision_probe(checkpoint_revision_probe),
        _check_no_duplicate_links(duplicate_links),
        _check_no_duplicate_time_links(duplicate_time_links),
    ]


def _check_no_turn_errors(turns: list[TurnCapture]) -> CheckResult:
    errors = [turn.error for turn in turns if turn.error]
    if errors:
        return CheckResult("真实 LLM turn 不抛异常", False, "; ".join(errors))
    return CheckResult("真实 LLM turn 不抛异常", True, "ok")


def _check_no_write_errors(turns: list[TurnCapture]) -> CheckResult:
    errors: list[str] = []
    for turn in turns:
        if turn.result is None:
            continue
        write_result = turn.result.metadata.get("write_result")
        if not isinstance(write_result, dict):
            continue
        failed = write_result.get("failed_operations")
        if isinstance(failed, list) and failed:
            errors.append(json.dumps(failed, ensure_ascii=False, default=str))
    if errors:
        return CheckResult("PostgreSQL normalized write 不失败", False, "; ".join(errors))
    return CheckResult("PostgreSQL normalized write 不失败", True, "ok")


def _check_event_entity_refs_do_not_carry_properties(
    turns: list[TurnCapture],
) -> CheckResult:
    violations: list[str] = []
    for turn in turns:
        if not turn.llm_output:
            continue
        try:
            payload = json.loads(turn.llm_output)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        for event in _list_payload(payload.get("event_candidates")):
            title = event.get("title") if isinstance(event, dict) else None
            for entity in _list_payload(event.get("entities")):
                if not isinstance(entity, dict):
                    continue
                properties = entity.get("properties")
                if isinstance(properties, list) and properties:
                    name = entity.get("name") or entity.get("client_id") or "<unknown>"
                    violations.append(
                        f"{turn.label}: event {title or '<unknown>'} entity {name} "
                        f"has {len(properties)} nested properties"
                    )
    if violations:
        return CheckResult(
            "event.entities 只携带实体引用不携带 properties",
            False,
            "; ".join(violations),
        )
    return CheckResult(
        "event.entities 只携带实体引用不携带 properties",
        True,
        "ok",
    )


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


def _check_checkpoint_revision_probe(payload: dict[str, Any]) -> CheckResult:
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, dict):
        return CheckResult("checkpoint revision as_of probe", False, "missing snapshots")
    c1 = _probe_texts(snapshots.get("c1"))
    c2 = _probe_texts(snapshots.get("c2"))
    c3 = _probe_texts(snapshots.get("c3"))
    inactive_c3 = snapshots.get("c3_include_inactive")
    inactive_statuses = [
        item.get("metadata", {}).get("status")
        for item in inactive_c3
        if isinstance(item, dict) and item.get("id") == payload.get("property_id")
    ] if isinstance(inactive_c3, list) else []
    failures: list[str] = []
    if "用户喜欢少糖" not in c1:
        failures.append("C1 missing 少糖")
    if "用户喜欢无糖" in c1:
        failures.append("C1 leaked 无糖")
    if "用户喜欢无糖" not in c2:
        failures.append("C2 missing 无糖")
    if "用户喜欢少糖" in c2:
        failures.append("C2 leaked 少糖")
    if "用户喜欢无糖" in c3:
        failures.append("C3 still active")
    if "invalidated" not in inactive_statuses:
        failures.append("C3 inactive view missing invalidated status")
    if failures:
        return CheckResult(
            "checkpoint revision as_of probe",
            False,
            "; ".join(failures),
        )
    return CheckResult("checkpoint revision as_of probe", True, "ok")


def _check_no_duplicate_links(duplicates: list[dict[str, Any]]) -> CheckResult:
    if duplicates:
        return CheckResult("memory_relations 无重复自然关系", False, json.dumps(duplicates))
    return CheckResult("memory_relations 无重复自然关系", True, "ok")


def _check_no_duplicate_time_links(duplicates: list[dict[str, Any]]) -> CheckResult:
    if duplicates:
        return CheckResult(
            "memory_time_links 无重复自然关系",
            False,
            json.dumps(duplicates),
        )
    return CheckResult("memory_time_links 无重复自然关系", True, "ok")


def _run_checkpoint_revision_probe(
    *,
    database_url: str,
    repository: PostgresPersistentMemoryRepository,
    user_id: str,
    session_id: str,
) -> dict[str, Any]:
    PostgresConversationStore(database_url)
    now = datetime.now(UTC).isoformat()
    checkpoint_ids = {
        "c1": f"chk_{session_id}_c1",
        "c2": f"chk_{session_id}_c2",
        "c3": f"chk_{session_id}_c3",
    }
    with repository.database.connect() as connection:
        with connection.transaction():
            connection.execute(
                """
                INSERT INTO users (id, username, display_name, metadata, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    user_id,
                    f"{user_id}_checkpoint_probe",
                    "Postgres real checkpoint probe",
                    Jsonb({}),
                    now,
                    now,
                ),
            )
            connection.execute(
                """
                INSERT INTO sessions (
                    id, user_id, title, metadata, created_at, updated_at,
                    head_checkpoint_id, root_session_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, NULL, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    session_id,
                    user_id,
                    "checkpoint revision probe",
                    Jsonb({"source": "postgres_real_runner"}),
                    now,
                    now,
                    session_id,
                ),
            )
            _insert_probe_checkpoint(
                connection,
                session_id=session_id,
                checkpoint_id=checkpoint_ids["c1"],
                parent_checkpoint_id=None,
                sequence=2,
                created_at=now,
            )
            _insert_probe_checkpoint(
                connection,
                session_id=session_id,
                checkpoint_id=checkpoint_ids["c2"],
                parent_checkpoint_id=checkpoint_ids["c1"],
                sequence=4,
                created_at=now,
            )
            _insert_probe_checkpoint(
                connection,
                session_id=session_id,
                checkpoint_id=checkpoint_ids["c3"],
                parent_checkpoint_id=checkpoint_ids["c2"],
                sequence=6,
                created_at=now,
            )
            _insert_probe_ancestry(
                connection,
                checkpoint_ids["c1"],
                [checkpoint_ids["c1"]],
            )
            _insert_probe_ancestry(
                connection,
                checkpoint_ids["c2"],
                [checkpoint_ids["c2"], checkpoint_ids["c1"]],
            )
            _insert_probe_ancestry(
                connection,
                checkpoint_ids["c3"],
                [checkpoint_ids["c3"], checkpoint_ids["c2"], checkpoint_ids["c1"]],
            )
            connection.execute(
                """
                UPDATE sessions
                SET head_checkpoint_id = %s, updated_at = %s
                WHERE id = %s
                """,
                (checkpoint_ids["c3"], now, session_id),
            )

    adapter = MemoryRecordPersistenceAdapter()
    entity_id = f"ent_{session_id}_user"
    property_id = f"prop_{session_id}_sugar"
    source_refs = [
        MemorySourceRef(
            source_type="message",
            source_id=f"msg_{session_id}_probe",
        )
    ]
    _save_probe_records(
        repository,
        adapter,
        [
            MemoryRecord(
                id=entity_id,
                memory_type="entity",
                text="用户",
                source_refs=source_refs,
                metadata={
                    "entity_type": "person",
                    "user_id": user_id,
                    "session_id": session_id,
                    "created_turn_id": f"turn_{session_id}_c1",
                    "created_checkpoint_id": checkpoint_ids["c1"],
                    "write_action": "create",
                },
            ),
            MemoryRecord(
                id=property_id,
                memory_type="property",
                text="用户喜欢少糖",
                source_refs=source_refs,
                metadata={
                    "attached_to_record_id": entity_id,
                    "property_type": "preference",
                    "user_id": user_id,
                    "session_id": session_id,
                    "created_turn_id": f"turn_{session_id}_c1",
                    "created_checkpoint_id": checkpoint_ids["c1"],
                    "write_action": "attach",
                },
            ),
        ],
    )
    _save_probe_records(
        repository,
        adapter,
        [
            MemoryRecord(
                id=property_id,
                memory_type="property",
                text="用户喜欢无糖",
                source_refs=source_refs,
                metadata={
                    "attached_to_record_id": entity_id,
                    "property_type": "preference",
                    "user_id": user_id,
                    "session_id": session_id,
                    "created_turn_id": f"turn_{session_id}_c2",
                    "created_checkpoint_id": checkpoint_ids["c2"],
                    "write_action": "update",
                },
            )
        ],
    )
    repository.update_object_status(
        property_id,
        "invalidated",
        metadata={
            "status": "invalidated",
            "write_action": "invalidate",
            "user_id": user_id,
            "session_id": session_id,
            "created_turn_id": f"turn_{session_id}_c3",
            "created_checkpoint_id": checkpoint_ids["c3"],
        },
    )
    return {
        "checkpoint_ids": checkpoint_ids,
        "entity_id": entity_id,
        "property_id": property_id,
        "snapshots": {
            label: [
                record.to_record()
                for record in repository.list_records_as_of(
                    checkpoint_id,
                    user_id=user_id,
                    session_id=session_id,
                )
            ]
            for label, checkpoint_id in checkpoint_ids.items()
        }
        | {
            "c3_include_inactive": [
                record.to_record()
                for record in repository.list_records_as_of(
                    checkpoint_ids["c3"],
                    user_id=user_id,
                    session_id=session_id,
                    include_inactive=True,
                )
            ]
        },
    }


def _insert_probe_checkpoint(
    connection,
    *,
    session_id: str,
    checkpoint_id: str,
    parent_checkpoint_id: str | None,
    sequence: int,
    created_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO conversation_checkpoints (
            id, session_id, parent_checkpoint_id, sequence, session_snapshot,
            active_memory_snapshot, metadata, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO NOTHING
        """,
        (
            checkpoint_id,
            session_id,
            parent_checkpoint_id,
            sequence,
            Jsonb({}),
            Jsonb({}),
            Jsonb({"source": "postgres_real_revision_probe"}),
            created_at,
        ),
    )


def _insert_probe_ancestry(
    connection,
    descendant_checkpoint_id: str,
    ancestors: list[str],
) -> None:
    for depth, ancestor_checkpoint_id in enumerate(ancestors):
        connection.execute(
            """
            INSERT INTO checkpoint_ancestry (
                ancestor_checkpoint_id, descendant_checkpoint_id, depth
            )
            VALUES (%s, %s, %s)
            ON CONFLICT (ancestor_checkpoint_id, descendant_checkpoint_id)
            DO UPDATE SET depth = EXCLUDED.depth
            """,
            (ancestor_checkpoint_id, descendant_checkpoint_id, depth),
        )


def _save_probe_records(
    repository: PostgresPersistentMemoryRepository,
    adapter: MemoryRecordPersistenceAdapter,
    records: list[MemoryRecord],
) -> None:
    build = adapter.build_bundle(records)
    if build.skipped_records:
        raise RuntimeError(
            "checkpoint revision probe skipped records: "
            + json.dumps(
                [item.to_record() for item in build.skipped_records],
                ensure_ascii=False,
            )
        )
    repository.save_bundle(build.bundle)


def _probe_texts(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        item["text"]
        for item in value
        if isinstance(item, dict) and isinstance(item.get("text"), str)
    ]


def _list_payload(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _load_normalized_rows(
    repository: PostgresPersistentMemoryRepository,
    user_id: str,
    session_id: str,
) -> dict[str, list[dict[str, Any]]]:
    with repository.database.connect() as connection:
        return {
            "events": _rows(
                connection,
                """
                SELECT e.id, e.title, e.summary, e.event_type, o.metadata
                FROM memory_events e
                JOIN memory_objects o ON o.id = e.id
                WHERE o.user_id = %s AND o.session_id = %s
                ORDER BY o.created_at
                """,
                (user_id, session_id),
            ),
            "descriptions": _rows(
                connection,
                "SELECT d.id, d.event_id, d.content, d.description_type, o.metadata "
                "FROM memory_descriptions d "
                "JOIN memory_objects o ON o.id = d.id "
                "WHERE o.user_id = %s AND o.session_id = %s ORDER BY o.created_at",
                (user_id, session_id),
            ),
            "entities": _rows(
                connection,
                """
                SELECT ent.id, ent.name, ent.entity_type, ent.identity_summary,
                       COALESCE(alias_rows.aliases, '[]'::jsonb) AS aliases,
                       o.metadata
                FROM memory_entities ent
                JOIN memory_objects o ON o.id = ent.id
                LEFT JOIN (
                  SELECT entity_id, jsonb_agg(alias ORDER BY position) AS aliases
                  FROM memory_entity_aliases
                  GROUP BY entity_id
                ) alias_rows ON alias_rows.entity_id = ent.id
                WHERE o.user_id = %s AND o.session_id = %s
                ORDER BY o.created_at
                """,
                (user_id, session_id),
            ),
            "properties": _rows(
                connection,
                "SELECT p.id, p.entity_id, p.content, p.property_type, o.metadata "
                "FROM memory_properties p "
                "JOIN memory_objects o ON o.id = p.id "
                "WHERE o.user_id = %s AND o.session_id = %s ORDER BY o.created_at",
                (user_id, session_id),
            ),
            "links": _rows(
                connection,
                """
                SELECT r.id, from_object.object_type AS from_type,
                       r.from_object_id AS from_id,
                       to_object.object_type AS to_type,
                       r.to_object_id AS to_id,
                       r.relation_type, r.reason, o.metadata
                FROM memory_relations r
                JOIN memory_objects o ON o.id = r.id
                JOIN memory_objects from_object ON from_object.id = r.from_object_id
                JOIN memory_objects to_object ON to_object.id = r.to_object_id
                WHERE o.user_id = %s OR o.session_id = %s
                ORDER BY o.created_at
                """,
                (user_id, session_id),
            ),
            "time_refs": _rows(
                connection,
                "SELECT tr.id, tr.raw_text, tr.time_kind, tr.timeline_kind, tr.certainty, o.metadata "
                "FROM memory_time_refs tr "
                "JOIN memory_objects o ON o.id = tr.id "
                "WHERE o.user_id = %s AND o.session_id = %s ORDER BY o.created_at",
                (user_id, session_id),
            ),
            "time_links": _rows(
                connection,
                """
                SELECT tl.id, target_object.object_type AS target_type,
                       tl.target_object_id AS target_id,
                       tl.time_ref_object_id AS time_ref_id,
                       tl.time_role, o.metadata
                FROM memory_time_links tl
                JOIN memory_objects o ON o.id = tl.id
                JOIN memory_objects target_object ON target_object.id = tl.target_object_id
                WHERE o.user_id = %s OR o.session_id = %s
                ORDER BY o.created_at
                """,
                (user_id, session_id),
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
            SELECT from_object_id, to_object_id, relation_type, count(*) AS count
            FROM memory_relations r
            JOIN memory_objects o ON o.id = r.id
            WHERE o.user_id = %s OR o.session_id = %s
            GROUP BY from_object_id, to_object_id, relation_type
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
            SELECT target_object_id, time_ref_object_id, time_role, count(*) AS count
            FROM memory_time_links tl
            JOIN memory_objects o ON o.id = tl.id
            WHERE o.session_id = %s
            GROUP BY target_object_id, time_ref_object_id, time_role
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
        "This test uses the real `LLMMemoryExtractor`, direct normalized "
        "PostgreSQL memory writes, and normalized retrieval. It targets the "
        "duplicate entity/property/relation pattern observed around "
        "`吃打抛饭经历`.",
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
    lines.extend(
        _json_section(
            "Checkpoint Revision Probe",
            capture.checkpoint_revision_probe,
        )
    )
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
        connection.execute(
            """
            DELETE FROM memory_objects
            WHERE user_id = %s OR session_id = %s
            """,
            (user_id, session_id),
        )
    try:
        PostgresConversationStore(database_url).delete_user(user_id, cascade=True)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
