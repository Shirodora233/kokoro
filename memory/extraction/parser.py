"""Parse LLM memory extraction responses."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from ..models import MemoryRecordType
from .schema import ALLOWED_MEMORY_TYPES, ExtractedMemoryCandidate

_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


class MemoryExtractionParseError(ValueError):
    """Raised when an extraction response cannot be parsed as JSON."""


def parse_extraction_response(content: str) -> list[ExtractedMemoryCandidate]:
    payload = _load_json_payload(content)
    raw_memories = payload if isinstance(payload, list) else payload.get("memories", [])
    if not isinstance(raw_memories, list):
        return []

    candidates: list[ExtractedMemoryCandidate] = []
    for raw_memory in raw_memories:
        candidate = _parse_candidate(raw_memory)
        if candidate:
            candidates.append(candidate)
    return candidates


def _load_json_payload(content: str) -> dict[str, Any] | list[Any]:
    text = _extract_json_text(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise MemoryExtractionParseError(
            "LLM extraction response is not valid JSON"
        ) from error

    if not isinstance(payload, (dict, list)):
        raise MemoryExtractionParseError(
            "LLM extraction response must be a JSON object or array"
        )
    return payload


def _extract_json_text(content: str) -> str:
    stripped = content.strip()
    fence_match = _CODE_FENCE_PATTERN.search(stripped)
    if fence_match:
        return fence_match.group(1).strip()

    if stripped.startswith("{") or stripped.startswith("["):
        return stripped

    object_start = stripped.find("{")
    object_end = stripped.rfind("}")
    if object_start != -1 and object_end != -1 and object_end > object_start:
        return stripped[object_start : object_end + 1]

    array_start = stripped.find("[")
    array_end = stripped.rfind("]")
    if array_start != -1 and array_end != -1 and array_end > array_start:
        return stripped[array_start : array_end + 1]

    return stripped


def _parse_candidate(raw_memory: Any) -> ExtractedMemoryCandidate | None:
    if not isinstance(raw_memory, dict):
        return None

    raw_type = raw_memory.get("memory_type") or raw_memory.get("type")
    if not isinstance(raw_type, str) or raw_type not in ALLOWED_MEMORY_TYPES:
        return None

    raw_text = raw_memory.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        return None

    raw_metadata = raw_memory.get("metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
    metadata.pop("canonical_key", None)
    metadata.pop("dedup_key", None)

    source_message_ids = _parse_string_list(raw_memory.get("source_message_ids"))
    raw_source_quote = raw_memory.get("source_quote")
    source_quote = None
    if isinstance(raw_source_quote, str) and raw_source_quote.strip():
        source_quote = raw_source_quote.strip()

    return ExtractedMemoryCandidate(
        memory_type=cast(MemoryRecordType, raw_type),
        text=raw_text.strip(),
        metadata=metadata,
        source_message_ids=source_message_ids,
        source_quote=source_quote,
    )


def _parse_string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
