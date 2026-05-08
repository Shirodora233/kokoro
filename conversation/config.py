"""Configuration loading for the conversation system."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


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
class LLMConfig:
    api_key: str
    base_url: str | None
    model: str
    temperature: float = 0.7
    max_context_messages: int = 30

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "LLMConfig":
        file_values = load_env_file(env_file)

        def read(name: str, default: str | None = None) -> str | None:
            return os.getenv(name) or file_values.get(name) or default

        api_key = read("LLM_API_KEY") or read("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Missing LLM_API_KEY or OPENAI_API_KEY in environment/.env")

        model = read("LLM_MODEL", "gpt-4.1-mini")
        if not model:
            raise RuntimeError("Missing LLM_MODEL in environment/.env")

        temperature = float(read("LLM_TEMPERATURE", "0.7") or "0.7")
        max_context_messages = int(read("LLM_MAX_CONTEXT_MESSAGES", "30") or "30")
        base_url = read("LLM_BASE_URL") or read("OPENAI_BASE_URL")

        return cls(
            api_key=api_key,
            base_url=base_url,
            model=model,
            temperature=temperature,
            max_context_messages=max_context_messages,
        )


@dataclass(frozen=True)
class StorageConfig:
    backend: Literal["json", "postgres"]
    database_url: str | None = None

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
        if not backend:
            backend = "postgres" if database_url else "json"
        if backend not in {"json", "postgres"}:
            raise RuntimeError("CONVERSATION_STORE must be either json or postgres")
        if backend == "postgres" and not database_url:
            raise RuntimeError(
                "CONVERSATION_DATABASE_URL or DATABASE_URL is required for postgres storage"
            )
        return cls(backend=backend, database_url=database_url)


def default_data_dir() -> Path:
    configured = os.getenv("CONVERSATION_DATA_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent / "data"
