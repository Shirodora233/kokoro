"""Validation for extracted memory candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import ExtractedMemoryCandidate

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
    "duration",
}


@dataclass(frozen=True)
class CandidateValidationResult:
    candidates: list[ExtractedMemoryCandidate]
    errors: list[str] = field(default_factory=list)


class MemoryCandidateValidator:
    """Validate candidate-level contracts that prompt instructions cannot ensure."""

    def validate(
        self,
        candidates: list[ExtractedMemoryCandidate],
    ) -> CandidateValidationResult:
        valid_by_client_id = self._valid_non_link_candidates(candidates)
        valid_links, link_errors = self._valid_time_links(candidates, valid_by_client_id)
        valid_event_ids = self._event_ids_with_time_links(valid_links)

        errors = list(link_errors)
        output: list[ExtractedMemoryCandidate] = []
        for candidate in candidates:
            if candidate.memory_type == "time_link":
                if candidate in valid_links:
                    output.append(candidate)
                continue

            if candidate.memory_type == "event":
                if not candidate.client_id:
                    errors.append("event dropped because client_id is missing")
                    continue
                if candidate.client_id not in valid_event_ids:
                    errors.append(
                        f"event {candidate.client_id} dropped because it has no valid time_link"
                    )
                    continue

            if candidate.client_id and candidate.client_id in valid_by_client_id:
                output.append(candidate)
                continue
            if not candidate.client_id and candidate.memory_type != "time_ref":
                output.append(candidate)

        return CandidateValidationResult(candidates=output, errors=errors)

    def _valid_non_link_candidates(
        self,
        candidates: list[ExtractedMemoryCandidate],
    ) -> dict[str, ExtractedMemoryCandidate]:
        valid: dict[str, ExtractedMemoryCandidate] = {}
        for candidate in candidates:
            if candidate.memory_type == "time_link":
                continue
            if candidate.memory_type == "time_ref" and not self._is_valid_time_ref(
                candidate
            ):
                continue
            if candidate.client_id:
                valid[candidate.client_id] = candidate
        return valid

    def _valid_time_links(
        self,
        candidates: list[ExtractedMemoryCandidate],
        valid_by_client_id: dict[str, ExtractedMemoryCandidate],
    ) -> tuple[list[ExtractedMemoryCandidate], list[str]]:
        valid_links: list[ExtractedMemoryCandidate] = []
        errors: list[str] = []
        for candidate in candidates:
            if candidate.memory_type != "time_link":
                continue
            metadata = candidate.metadata
            target_id = self._string_value(metadata, "target_client_id")
            time_ref_id = self._string_value(metadata, "time_ref_client_id")
            time_role = self._string_value(metadata, "time_role")
            if not target_id or not time_ref_id or not time_role:
                errors.append("time_link dropped because required metadata is missing")
                continue
            if time_role not in ALLOWED_TIME_ROLES:
                errors.append(f"time_link dropped because time_role={time_role!r}")
                continue
            if target_id not in valid_by_client_id:
                errors.append(f"time_link dropped because target {target_id!r} is invalid")
                continue
            target = valid_by_client_id[target_id]
            if target.memory_type == "time_ref":
                errors.append("time_link dropped because target cannot be time_ref")
                continue
            if time_ref_id not in valid_by_client_id:
                errors.append(
                    f"time_link dropped because time_ref {time_ref_id!r} is invalid"
                )
                continue
            time_ref = valid_by_client_id[time_ref_id]
            if time_ref.memory_type != "time_ref":
                errors.append("time_link dropped because time_ref target is not time_ref")
                continue
            valid_links.append(candidate)
        return valid_links, errors

    def _event_ids_with_time_links(
        self,
        links: list[ExtractedMemoryCandidate],
    ) -> set[str]:
        return {
            link.metadata["target_client_id"]
            for link in links
            if isinstance(link.metadata.get("target_client_id"), str)
        }

    def _is_valid_time_ref(self, candidate: ExtractedMemoryCandidate) -> bool:
        metadata = candidate.metadata
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
