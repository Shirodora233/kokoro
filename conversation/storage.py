"""JSON document persistence with database-like table boundaries."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from .models import ChatSession, Message, User


def _table_template(
    table: str,
    primary_key: str,
    columns: list[str],
    foreign_keys: dict[str, str] | None = None,
    indexes: list[list[str]] | None = None,
) -> dict[str, Any]:
    return {
        "table": table,
        "primary_key": primary_key,
        "columns": columns,
        "foreign_keys": foreign_keys or {},
        "indexes": indexes or [],
        "records": [],
    }


TABLE_TEMPLATES: dict[str, dict[str, Any]] = {
    "users": _table_template(
        table="users",
        primary_key="id",
        columns=["id", "username", "display_name", "metadata", "created_at", "updated_at"],
        indexes=[["username"]],
    ),
    "sessions": _table_template(
        table="sessions",
        primary_key="id",
        columns=[
            "id",
            "user_id",
            "title",
            "system_prompt",
            "model",
            "temperature",
            "max_context_messages",
            "context_start_index",
            "metadata",
            "created_at",
            "updated_at",
            "archived_at",
        ],
        foreign_keys={"user_id": "users.id"},
        indexes=[["user_id"], ["updated_at"]],
    ),
    "messages": _table_template(
        table="messages",
        primary_key="id",
        columns=[
            "id",
            "session_id",
            "user_id",
            "role",
            "content",
            "model",
            "token_usage",
            "metadata",
            "created_at",
        ],
        foreign_keys={"session_id": "sessions.id", "user_id": "users.id"},
        indexes=[["session_id", "created_at"], ["user_id"]],
    ),
}


class JsonTable:
    def __init__(self, path: Path, template: dict[str, Any]) -> None:
        self.path = path
        self.template = template

    def ensure(self) -> None:
        if self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.write(deepcopy(self.template))

    def read(self) -> dict[str, Any]:
        self.ensure()
        with self.path.open("r", encoding="utf-8") as file:
            return json.load(file)

    def write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        tmp_path.replace(self.path)


class JsonConversationStore:
    """Repository implementation that persists normalized tables as JSON files."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self._lock = RLock()
        self._tables = {
            name: JsonTable(self.data_dir / f"{name}.json", template)
            for name, template in TABLE_TEMPLATES.items()
        }
        self._schema_path = self.data_dir / "schema.json"
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            for table in self._tables.values():
                table.ensure()
            if not self._schema_path.exists():
                schema = {
                    "name": "conversation_json_store",
                    "version": 1,
                    "tables": {
                        name: {
                            key: value
                            for key, value in template.items()
                            if key != "records"
                        }
                        for name, template in TABLE_TEMPLATES.items()
                    },
                }
                JsonTable(self._schema_path, schema).write(schema)

    def create_user(self, user: User) -> User:
        with self._lock:
            table = self._read("users")
            records = table["records"]
            if any(record["id"] == user.id for record in records):
                raise ValueError(f"User id already exists: {user.id}")
            if any(record["username"] == user.username for record in records):
                raise ValueError(f"Username already exists: {user.username}")
            records.append(user.to_record())
            self._write("users", table)
            return user

    def get_user(self, user_id: str) -> User | None:
        record = self._find_one("users", lambda item: item["id"] == user_id)
        return User.from_record(record) if record else None

    def find_user_by_username(self, username: str) -> User | None:
        record = self._find_one("users", lambda item: item["username"] == username)
        return User.from_record(record) if record else None

    def list_users(self) -> list[User]:
        return [User.from_record(record) for record in self._read("users")["records"]]

    def delete_user(self, user_id: str, cascade: bool = False) -> dict[str, int]:
        with self._lock:
            users_table = self._read("users")
            sessions_table = self._read("sessions")
            messages_table = self._read("messages")

            users = users_table["records"]
            user_index = next(
                (index for index, record in enumerate(users) if record["id"] == user_id),
                None,
            )
            if user_index is None:
                raise ValueError(f"Unknown user_id: {user_id}")

            user_session_ids = {
                record["id"]
                for record in sessions_table["records"]
                if record["user_id"] == user_id
            }
            user_message_count = sum(
                1
                for record in messages_table["records"]
                if record.get("user_id") == user_id
            )
            if (user_session_ids or user_message_count) and not cascade:
                raise ValueError("User has related sessions/messages; enable cascade to delete them")

            deleted_sessions = 0
            deleted_messages = 0
            if cascade:
                original_sessions = len(sessions_table["records"])
                sessions_table["records"] = [
                    record
                    for record in sessions_table["records"]
                    if record["user_id"] != user_id
                ]
                deleted_sessions = original_sessions - len(sessions_table["records"])

                original_messages = len(messages_table["records"])
                messages_table["records"] = [
                    record
                    for record in messages_table["records"]
                    if record["session_id"] not in user_session_ids
                    and record.get("user_id") != user_id
                ]
                deleted_messages = original_messages - len(messages_table["records"])

            users.pop(user_index)
            self._write("messages", messages_table)
            self._write("sessions", sessions_table)
            self._write("users", users_table)
            return {"users": 1, "sessions": deleted_sessions, "messages": deleted_messages}

    def create_session(self, session: ChatSession) -> ChatSession:
        with self._lock:
            if not self.get_user(session.user_id):
                raise ValueError(f"Unknown user_id for session: {session.user_id}")
            table = self._read("sessions")
            records = table["records"]
            if any(record["id"] == session.id for record in records):
                raise ValueError(f"Session id already exists: {session.id}")
            records.append(session.to_record())
            self._write("sessions", table)
            return session

    def get_session(self, session_id: str) -> ChatSession | None:
        record = self._find_one("sessions", lambda item: item["id"] == session_id)
        return ChatSession.from_record(record) if record else None

    def update_session(self, session: ChatSession) -> ChatSession:
        with self._lock:
            table = self._read("sessions")
            records = table["records"]
            for index, record in enumerate(records):
                if record["id"] == session.id:
                    records[index] = session.to_record()
                    self._write("sessions", table)
                    return session
            raise ValueError(f"Unknown session_id: {session.id}")

    def list_sessions(self, user_id: str | None = None) -> list[ChatSession]:
        records = self._read("sessions")["records"]
        if user_id is not None:
            records = [record for record in records if record["user_id"] == user_id]
        sessions = [ChatSession.from_record(record) for record in records]
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def delete_session(self, session_id: str) -> dict[str, int]:
        with self._lock:
            sessions_table = self._read("sessions")
            messages_table = self._read("messages")

            original_sessions = len(sessions_table["records"])
            sessions_table["records"] = [
                record
                for record in sessions_table["records"]
                if record["id"] != session_id
            ]
            deleted_sessions = original_sessions - len(sessions_table["records"])
            if deleted_sessions == 0:
                raise ValueError(f"Unknown session_id: {session_id}")

            original_messages = len(messages_table["records"])
            messages_table["records"] = [
                record
                for record in messages_table["records"]
                if record["session_id"] != session_id
            ]
            deleted_messages = original_messages - len(messages_table["records"])

            self._write("messages", messages_table)
            self._write("sessions", sessions_table)
            return {"users": 0, "sessions": deleted_sessions, "messages": deleted_messages}

    def append_message(self, message: Message) -> Message:
        with self._lock:
            session = self.get_session(message.session_id)
            if not session:
                raise ValueError(f"Unknown session_id for message: {message.session_id}")
            if message.user_id and not self.get_user(message.user_id):
                raise ValueError(f"Unknown user_id for message: {message.user_id}")

            table = self._read("messages")
            records = table["records"]
            if any(record["id"] == message.id for record in records):
                raise ValueError(f"Message id already exists: {message.id}")
            records.append(message.to_record())
            self._write("messages", table)

            session.touch()
            self.update_session(session)
            return message

    def list_messages(self, session_id: str) -> list[Message]:
        records = [
            record
            for record in self._read("messages")["records"]
            if record["session_id"] == session_id
        ]
        messages = [Message.from_record(record) for record in records]
        return sorted(messages, key=lambda item: item.created_at)

    def delete_all(self) -> dict[str, int]:
        with self._lock:
            counts: dict[str, int] = {}
            for table_name in ("messages", "sessions", "users"):
                table = self._read(table_name)
                counts[table_name] = len(table["records"])
                table["records"] = []
                self._write(table_name, table)
            return counts

    def _read(self, table: str) -> dict[str, Any]:
        with self._lock:
            return self._tables[table].read()

    def _write(self, table: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._tables[table].write(data)

    def _find_one(
        self,
        table: str,
        predicate: Callable[[dict[str, Any]], bool],
    ) -> dict[str, Any] | None:
        with self._lock:
            for record in self._read(table)["records"]:
                if predicate(record):
                    return record
        return None
