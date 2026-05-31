"""Convert PostgreSQL rows into domain models."""

from __future__ import annotations

from typing import Any, Mapping

from conversation.models import (
    ChatSession,
    ConversationCheckpoint,
    ConversationTurn,
    Message,
    SessionBranch,
    User,
)


def user_from_row(row: Mapping[str, Any]) -> User:
    return User.from_record(
        {
            "id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "metadata": row["metadata"] or {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


def session_from_row(row: Mapping[str, Any]) -> ChatSession:
    return ChatSession.from_record(
        {
            "id": row["id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "system_prompt": row["system_prompt"],
            "model": row["model"],
            "temperature": row["temperature"],
            "max_context_messages": row["max_context_messages"],
            "context_start_index": row["context_start_index"],
            "metadata": row["metadata"] or {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "archived_at": row["archived_at"],
        }
    )


def message_from_row(row: Mapping[str, Any]) -> Message:
    metadata = dict(row["metadata"] or {})
    for key in ("turn_id", "checkpoint_id", "sequence", "status"):
        if key in row and row[key] is not None:
            metadata.setdefault(key, row[key])
    return Message.from_record(
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "user_id": row["user_id"],
            "role": row["role"],
            "content": row["content"],
            "model": row["model"],
            "token_usage": row["token_usage"] or {},
            "metadata": metadata,
            "created_at": row["created_at"],
        }
    )


def turn_from_row(row: Mapping[str, Any]) -> ConversationTurn:
    return ConversationTurn.from_record(
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "user_message_id": row["user_message_id"],
            "assistant_message_id": row["assistant_message_id"],
            "checkpoint_id": row["checkpoint_id"],
            "status": row["status"],
            "idempotency_key": row["idempotency_key"],
            "debug_trace_id": row["debug_trace_id"],
            "memory_status": row["memory_status"],
            "error": row["error"],
            "metadata": row["metadata"] or {},
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
    )


def checkpoint_from_row(row: Mapping[str, Any]) -> ConversationCheckpoint:
    return ConversationCheckpoint.from_record(
        {
            "id": row["id"],
            "session_id": row["session_id"],
            "turn_id": row["turn_id"],
            "parent_checkpoint_id": row["parent_checkpoint_id"],
            "assistant_message_id": row["assistant_message_id"],
            "sequence": row["sequence"],
            "label": row["label"],
            "session_snapshot": row["session_snapshot"] or {},
            "active_memory_snapshot": row["active_memory_snapshot"] or {},
            "metadata": row["metadata"] or {},
            "created_at": row["created_at"],
        }
    )


def branch_from_row(row: Mapping[str, Any]) -> SessionBranch:
    return SessionBranch.from_record(
        {
            "session_id": row["session_id"],
            "root_session_id": row["root_session_id"],
            "parent_session_id": row["parent_session_id"],
            "base_checkpoint_id": row["base_checkpoint_id"],
            "base_sequence": row["base_sequence"],
            "metadata": row["metadata"] or {},
            "created_at": row["created_at"],
        }
    )
