"""Internal DTOs for memory extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, get_args

from ..models import MemoryRecordType

ALLOWED_MEMORY_TYPES = set(get_args(MemoryRecordType))


@dataclass(frozen=True)
class ExtractedMemoryCandidate:
    memory_type: MemoryRecordType
    text: str
    client_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_message_ids: list[str] = field(default_factory=list)
    source_quote: str | None = None
