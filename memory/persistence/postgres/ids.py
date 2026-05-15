"""Id helpers for normalized memory persistence."""

from __future__ import annotations

from uuid import uuid4

from ...models import MemoryRecordType
from ...storage.ids import new_memory_id


def new_persistent_id(memory_type: MemoryRecordType) -> str:
    return new_memory_id(memory_type)


def new_source_id() -> str:
    return f"src_{uuid4().hex}"
