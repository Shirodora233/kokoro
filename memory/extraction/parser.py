"""Parse LLM aggregate memory extraction responses."""

from __future__ import annotations

import json
import re
from typing import Any

from .schema import (
    DescriptionCandidate,
    EntityCandidate,
    EventCandidate,
    ExtractionCandidateBatch,
    PropertyCandidate,
    SourceHint,
    TimeCandidate,
)

_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_FORBIDDEN_METADATA_KEYS = {"canonical_key", "dedup_key"}


class MemoryExtractionParseError(ValueError):
    """Raised when an extraction response cannot be parsed as JSON."""


def parse_extraction_response(content: str) -> ExtractionCandidateBatch:
    payload = _load_json_payload(content)
    if not isinstance(payload, dict):
        raise MemoryExtractionParseError("LLM extraction response must be a JSON object")

    return ExtractionCandidateBatch(
        event_candidates=_parse_event_candidates(payload.get("event_candidates")),
        entity_candidates=_parse_entity_candidates(payload.get("entity_candidates")),
        metadata=_clean_metadata(payload.get("metadata")),
    )


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


def _parse_event_candidates(value: Any) -> list[EventCandidate]:
    if not isinstance(value, list):
        return []
    events: list[EventCandidate] = []
    for item in value:
        event = _parse_event_candidate(item)
        if event:
            events.append(event)
    return events


def _parse_event_candidate(value: Any) -> EventCandidate | None:
    if not isinstance(value, dict):
        return None

    title = _string_value(value.get("title"))
    if not title:
        return None

    return EventCandidate(
        client_id=_string_value(value.get("client_id")),
        title=title,
        summary=_string_value(value.get("summary")),
        event_type=_string_value(value.get("event_type")),
        time=_parse_time_candidate(value.get("time")),
        descriptions=_parse_description_candidates(value.get("descriptions")),
        entities=_parse_entity_candidates(value.get("entities")),
        source=_parse_source(value),
        metadata=_clean_metadata(value.get("metadata")),
    )


def _parse_description_candidates(value: Any) -> list[DescriptionCandidate]:
    if not isinstance(value, list):
        return []
    descriptions: list[DescriptionCandidate] = []
    for item in value:
        description = _parse_description_candidate(item)
        if description:
            descriptions.append(description)
    return descriptions


def _parse_description_candidate(value: Any) -> DescriptionCandidate | None:
    if not isinstance(value, dict):
        return None

    text = _string_value(value.get("text"))
    if not text:
        return None

    return DescriptionCandidate(
        client_id=_string_value(value.get("client_id")),
        text=text,
        description_type=_string_value(value.get("description_type")),
        time=_parse_time_candidate(value.get("time")),
        source=_parse_source(value),
        metadata=_clean_metadata(value.get("metadata")),
    )


def _parse_entity_candidates(value: Any) -> list[EntityCandidate]:
    if not isinstance(value, list):
        return []
    entities: list[EntityCandidate] = []
    for item in value:
        entity = _parse_entity_candidate(item)
        if entity:
            entities.append(entity)
    return entities


def _parse_entity_candidate(value: Any) -> EntityCandidate | None:
    if not isinstance(value, dict):
        return None

    name = _string_value(value.get("name"))
    if not name:
        return None

    return EntityCandidate(
        client_id=_string_value(value.get("client_id")),
        name=name,
        entity_type=_string_value(value.get("entity_type")),
        identity_summary=_string_value(value.get("identity_summary")),
        aliases=_parse_string_list(value.get("aliases")),
        properties=_parse_property_candidates(value.get("properties")),
        source=_parse_source(value),
        metadata=_clean_metadata(value.get("metadata")),
    )


def _parse_property_candidates(value: Any) -> list[PropertyCandidate]:
    if not isinstance(value, list):
        return []
    properties: list[PropertyCandidate] = []
    for item in value:
        prop = _parse_property_candidate(item)
        if prop:
            properties.append(prop)
    return properties


def _parse_property_candidate(value: Any) -> PropertyCandidate | None:
    if not isinstance(value, dict):
        return None

    text = _string_value(value.get("text"))
    if not text:
        return None

    return PropertyCandidate(
        client_id=_string_value(value.get("client_id")),
        text=text,
        property_type=_string_value(value.get("property_type")),
        time=_parse_time_candidate(value.get("time")),
        source=_parse_source(value),
        metadata=_clean_metadata(value.get("metadata")),
    )


def _parse_time_candidate(value: Any) -> TimeCandidate | None:
    if not isinstance(value, dict):
        return None
    if _string_value(value.get("role")) == "same_as_parent":
        return TimeCandidate(role="same_as_parent")

    return TimeCandidate(
        client_id=_string_value(value.get("client_id")),
        role=_string_value(value.get("role")),
        raw_text=_string_value(value.get("raw_text")),
        time_kind=_string_value(value.get("time_kind")),
        timeline_kind=_string_value(value.get("timeline_kind")),
        certainty=_string_value(value.get("certainty")),
        anchor_timezone=_string_value(value.get("anchor_timezone")),
        anchor_utc_offset=_string_value(value.get("anchor_utc_offset")),
        anchor_message_id=_string_value(value.get("anchor_message_id")),
        resolved_start=_string_value(value.get("resolved_start")),
        resolved_end=_string_value(value.get("resolved_end")),
        granularity=_string_value(value.get("granularity")),
        description=_string_value(value.get("description")),
        duration_text=_string_value(value.get("duration_text")),
        recurrence_text=_string_value(value.get("recurrence_text")),
        source=_parse_source(value),
        metadata=_clean_metadata(value.get("metadata")),
    )


def _parse_source(value: dict[str, Any]) -> SourceHint:
    return SourceHint(
        source_message_ids=_parse_string_list(value.get("source_message_ids")),
        source_quote=_string_value(value.get("source_quote")),
    )


def _clean_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: raw_value
        for key, raw_value in value.items()
        if key not in _FORBIDDEN_METADATA_KEYS
    }


def _parse_string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _string_value(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
