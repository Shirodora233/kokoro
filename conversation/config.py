"""Configuration loading for the conversation system."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _strip_optional_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def load_env_file(path: str | Path = ".env") -> dict[str, str]:
    """Load simple KEY=VALUE entries from a .env file without extra dependencies."""

    env_path = Path(path)
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = _strip_optional_quotes(value)
    return values


@dataclass(frozen=True)
class ConversationRuntimeConfig:
    timezone: str = "UTC"

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "ConversationRuntimeConfig":
        file_values = load_env_file(env_file)

        def read(name: str, default: str | None = None) -> str | None:
            return os.getenv(name) or file_values.get(name) or default

        timezone = read("CONVERSATION_TIMEZONE") or read("TZ") or "UTC"
        return cls(timezone=timezone)


@dataclass(frozen=True)
class StorageConfig:
    database_url: str

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "StorageConfig":
        file_values = load_env_file(env_file)

        def read(name: str, default: str | None = None) -> str | None:
            return os.getenv(name) or file_values.get(name) or default

        database_url = (
            read("CONVERSATION_DATABASE_URL")
            or read("DATABASE_URL")
            or read("POSTGRES_DATABASE_URL")
        )
        backend = (read("CONVERSATION_STORE") or "").lower()
        if backend and backend != "postgres":
            raise RuntimeError("CONVERSATION_STORE must be postgres")
        if not database_url:
            raise RuntimeError(
                "CONVERSATION_DATABASE_URL or DATABASE_URL is required for postgres storage"
            )
        return cls(database_url=database_url)
