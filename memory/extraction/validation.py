"""Validation for aggregate extracted memory candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import (
    EntityCandidate,
    EventCandidate,
    ExtractionCandidateBatch,
    PropertyCandidate,
    TimeCandidate,
)

TIME_REF_BASE_FIELDS = {
    "raw_text",
    "time_kind",
    "timeline_kind",
    "certainty",
    "anchor_timezone",
    "anchor_utc_offset",
}
TIME_KIND_REQUIRED_FIELDS: dict[str, set[str]] = {
    "exact": {"resolved_start", "granularity"},
    "relative": {"anchor_message_id", "resolved_start", "granularity"},
    "vague": {"description"},
    "duration": {"duration_text"},
    "recurring": {"recurrence_text"},
}
ALLOWED_TIME_KINDS = set(TIME_KIND_REQUIRED_FIELDS)
ALLOWED_TIMELINE_KINDS = {"real_world", "fictional"}
ALLOWED_CERTAINTY = {"resolved", "inferred", "vague", "unknown"}
ALLOWED_TIME_ROLES = {
    "occurred_at",
    "started_at",
    "ended_at",
    "scheduled_at",
    "valid_from",
    "valid_until",
    "mentioned_at",
    "observed_at",
    "recurs_at",
    "duration",
}


@dataclass(frozen=True)
class CandidateValidationResult:
    batch: ExtractionCandidateBatch
    errors: list[str] = field(default_factory=list)


class MemoryCandidateValidator:
    """Validate aggregate candidate shape without doing reconciliation."""

    def validate(
        self,
        batch: ExtractionCandidateBatch,
    ) -> CandidateValidationResult:
        errors: list[str] = []
        events: list[EventCandidate] = []
        entities: list[EntityCandidate] = []

        for event in batch.event_candidates:
            if not event.descriptions:
                errors.append(f"event {event.client_id or event.title!r} has no descriptions")
                continue
            events.append(event)
            errors.extend(self._time_errors(event.time, f"event {event.client_id}"))
            for description in event.descriptions:
                errors.extend(
                    self._time_errors(
                        description.time,
                        f"description {description.client_id}",
                        allow_same_as_parent=True,
                    )
                )
            for entity in event.entities:
                errors.extend(self._entity_errors(entity))

        for entity in batch.entity_candidates:
            errors.extend(self._entity_errors(entity))
            entities.append(entity)

        return CandidateValidationResult(
            batch=ExtractionCandidateBatch(
                event_candidates=events,
                entity_candidates=entities,
                metadata=batch.metadata,
            ),
            errors=errors,
        )

    def _entity_errors(self, entity: EntityCandidate) -> list[str]:
        errors: list[str] = []
        if not entity.name.strip():
            errors.append("entity has empty name")
        for prop in entity.properties:
            errors.extend(self._property_errors(prop))
        return errors

    def _property_errors(self, prop: PropertyCandidate) -> list[str]:
        return self._time_errors(prop.time, f"property {prop.client_id}")

    def _time_errors(
        self,
        time: TimeCandidate | None,
        label: str,
        allow_same_as_parent: bool = False,
    ) -> list[str]:
        if time is None:
            return []
        if allow_same_as_parent and time.role == "same_as_parent":
            return []
        if not self._is_valid_time_ref(time):
            return [f"{label} has invalid time contract"]
        if time.role and time.role not in ALLOWED_TIME_ROLES:
            return [f"{label} has invalid time role {time.role!r}"]
        return []

    def _is_valid_time_ref(self, time: TimeCandidate) -> bool:
        metadata = self._time_metadata(time)
        if not self._has_required_fields(metadata, TIME_REF_BASE_FIELDS):
            return False

        time_kind = self._string_value(metadata, "time_kind")
        timeline_kind = self._string_value(metadata, "timeline_kind")
        certainty = self._string_value(metadata, "certainty")
        if time_kind not in ALLOWED_TIME_KINDS:
            return False
        if timeline_kind not in ALLOWED_TIMELINE_KINDS:
            return False
        if certainty not in ALLOWED_CERTAINTY:
            return False

        required = TIME_KIND_REQUIRED_FIELDS[time_kind]
        return self._has_required_fields(metadata, required)

    def _time_metadata(self, time: TimeCandidate) -> dict[str, Any]:
        metadata = dict(time.metadata)
        for field_name in [
            "raw_text",
            "time_kind",
            "timeline_kind",
            "certainty",
            "anchor_timezone",
            "anchor_utc_offset",
            "anchor_message_id",
            "resolved_start",
            "resolved_end",
            "granularity",
            "description",
            "duration_text",
            "recurrence_text",
        ]:
            value = getattr(time, field_name)
            if value is not None:
                metadata.setdefault(field_name, value)
        return metadata

    def _has_required_fields(
        self,
        metadata: dict[str, Any],
        fields: set[str],
    ) -> bool:
        return all(self._string_value(metadata, field_name) for field_name in fields)

    def _string_value(self, metadata: dict[str, Any], key: str) -> str | None:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None
