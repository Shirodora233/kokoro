"""Memory storage id helpers."""

from __future__ import annotations

from uuid import uuid4

from ..models import MemoryRecordType

_ID_PREFIXES: dict[MemoryRecordType, str] = {
    "event": "evt",
    "description": "desc",
    "entity": "ent",
    "property": "prop",
    "link": "link",
    "time_ref": "time",
    "time_link": "tlink",
    "summary": "sum",
}


def new_memory_id(memory_type: MemoryRecordType) -> str:
    prefix = _ID_PREFIXES.get(memory_type, "mem")
    return f"{prefix}_{uuid4().hex}"
