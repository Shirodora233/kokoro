"""Migrate normalized JSON conversation tables into PostgreSQL."""

from __future__ import annotations

import argparse
from pathlib import Path

from conversation.config import StorageConfig, default_data_dir
from conversation.models import ChatSession, Message
from conversation.storage import JsonConversationStore

from .postgres import PostgresConversationStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate JSON conversation data to PostgreSQL")
    parser.add_argument("--env-file", default=".env", help="Path to .env file")
    parser.add_argument("--data-dir", default=None, help="Directory containing JSON table files")
    parser.add_argument("--database-url", default=None, help="PostgreSQL connection URL")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing PostgreSQL conversation rows before importing",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    data_dir = Path(args.data_dir) if args.data_dir else default_data_dir()
    storage_config = StorageConfig.from_env(args.env_file)
    database_url = args.database_url or storage_config.database_url
    if not database_url:
        raise SystemExit("error: --database-url or CONVERSATION_DATABASE_URL is required")

    source = JsonConversationStore(data_dir)
    target = PostgresConversationStore(database_url)

    users = source.list_users()
    sessions = source.list_sessions()
    messages = _all_messages(source, sessions)
    imported = target.import_records(
        users=users,
        sessions=sessions,
        messages=messages,
        replace=args.replace,
    )
    print(
        "imported "
        f"users={imported['users']} "
        f"sessions={imported['sessions']} "
        f"messages={imported['messages']}"
    )


def _all_messages(
    source: JsonConversationStore,
    sessions: list[ChatSession],
) -> list[Message]:
    messages: list[Message] = []
    for session in sessions:
        messages.extend(source.list_messages(session.id))
    return messages


if __name__ == "__main__":
    main()
