"""Conversation storage facade backed by PostgreSQL repositories."""

from __future__ import annotations

from conversation.models import ChatSession, Message, User

from .checkpoint_repository import PostgresCheckpointRepository
from .connection import PostgresDatabase
from .debug_repository import PostgresConversationDebugRepository
from .maintenance_repository import PostgresMaintenanceRepository
from .message_repository import PostgresMessageRepository
from .session_repository import PostgresSessionRepository
from .user_repository import PostgresUserRepository


class PostgresConversationStore:
    """PostgreSQL conversation repository facade."""

    def __init__(self, database_url: str) -> None:
        self.database = PostgresDatabase(database_url)
        self.ensure_schema()
        self.users = PostgresUserRepository(self.database)
        self.sessions = PostgresSessionRepository(self.database)
        self.messages = PostgresMessageRepository(self.database)
        self.checkpoints = PostgresCheckpointRepository(self.database)
        self.debug = PostgresConversationDebugRepository(self.database)
        self.maintenance = PostgresMaintenanceRepository(self.database)

    def ensure_schema(self) -> None:
        self.database.ensure_schema()

    def create_user(self, user: User) -> User:
        return self.users.create_user(user)

    def get_user(self, user_id: str) -> User | None:
        return self.users.get_user(user_id)

    def find_user_by_username(self, username: str) -> User | None:
        return self.users.find_user_by_username(username)

    def list_users(self) -> list[User]:
        return self.users.list_users()

    def delete_user(self, user_id: str, cascade: bool = False) -> dict[str, int]:
        return self.users.delete_user(user_id=user_id, cascade=cascade)

    def create_session(self, session: ChatSession) -> ChatSession:
        return self.sessions.create_session(session)

    def get_session(self, session_id: str) -> ChatSession | None:
        return self.sessions.get_session(session_id)

    def update_session(self, session: ChatSession) -> ChatSession:
        return self.sessions.update_session(session)

    def list_sessions(self, user_id: str | None = None) -> list[ChatSession]:
        return self.sessions.list_sessions(user_id=user_id)

    def delete_session(self, session_id: str) -> dict[str, int]:
        return self.sessions.delete_session(session_id)

    def append_message(self, message: Message) -> Message:
        return self.messages.append_message(message)

    def list_messages(self, session_id: str) -> list[Message]:
        return self.checkpoints.visible_messages(session_id)

    def delete_all(self) -> dict[str, int]:
        return self.maintenance.delete_all()
