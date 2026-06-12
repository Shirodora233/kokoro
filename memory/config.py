"""Configuration for the memory runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _strip_optional_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _load_env_file(path: str | Path = ".env") -> dict[str, str]:
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
        if key:
            values[key] = _strip_optional_quotes(value)
    return values


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class MemoryRuntimeConfig:
    extraction_enabled: bool = True
    extraction_model: str | None = None
    extraction_temperature: float = 0.0
    extraction_max_context_messages: int = 20
    reconciliation_mode: str = "llm"
    reconciliation_model: str | None = None
    reconciliation_temperature: float = 0.0
    reconciliation_max_repair_attempts: int = 1
    debug_enabled: bool = True
    debug_max_traces: int = 50
    debug_max_raw_chars: int = 200_000

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "MemoryRuntimeConfig":
        file_values = _load_env_file(env_file)

        def read(name: str, default: str | None = None) -> str | None:
            return os.getenv(name) or file_values.get(name) or default

        enabled = _parse_bool(read("MEMORY_EXTRACTION_ENABLED"), default=True)
        model = read("MEMORY_EXTRACTION_MODEL")
        temperature = float(read("MEMORY_EXTRACTION_TEMPERATURE", "0.0") or "0.0")
        max_context_messages = int(
            read("MEMORY_EXTRACTION_MAX_CONTEXT_MESSAGES", "20") or "20"
        )
        reconciliation_mode = (
            read("MEMORY_RECONCILIATION_MODE", "llm") or "llm"
        ).strip().lower()
        reconciliation_model = read("MEMORY_RECONCILIATION_MODEL")
        reconciliation_temperature = float(
            read("MEMORY_RECONCILIATION_TEMPERATURE", "0.0") or "0.0"
        )
        reconciliation_max_repair_attempts = int(
            read("MEMORY_RECONCILIATION_MAX_REPAIR_ATTEMPTS", "1") or "1"
        )
        debug_enabled = _parse_bool(read("MEMORY_DEBUG_ENABLED"), default=True)
        debug_max_traces = int(read("MEMORY_DEBUG_MAX_TRACES", "50") or "50")
        debug_max_raw_chars = int(
            read("MEMORY_DEBUG_MAX_RAW_CHARS", "200000") or "200000"
        )
        return cls(
            extraction_enabled=enabled,
            extraction_model=model,
            extraction_temperature=temperature,
            extraction_max_context_messages=max_context_messages,
            reconciliation_mode=reconciliation_mode,
            reconciliation_model=reconciliation_model,
            reconciliation_temperature=reconciliation_temperature,
            reconciliation_max_repair_attempts=reconciliation_max_repair_attempts,
            debug_enabled=debug_enabled,
            debug_max_traces=debug_max_traces,
            debug_max_raw_chars=debug_max_raw_chars,
        )
