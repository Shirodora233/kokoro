"""Parse LLM reconciliation responses."""

from __future__ import annotations

import json
import re
from typing import Any, cast

from ..models import ReconciliationConfidence, WriteAction
from .models import LLMReconciliationDecision, LLMReconciliationResponse

_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_ACTIONS = {
    "create",
    "reuse",
    "attach",
    "update",
    "merge",
    "invalidate",
    "flag_conflict",
    "ignore",
}
_CONFIDENCE = {"low", "medium", "high"}


class LLMReconciliationParseError(ValueError):
    """Raised when an LLM reconciliation response cannot be parsed."""


class LLMReconciliationParser:
    """Parse strict JSON decisions from an LLM response."""

    def parse(self, content: str) -> LLMReconciliationResponse:
        payload = _load_json_payload(content)
        if not isinstance(payload, dict):
            raise LLMReconciliationParseError(
                "LLM reconciliation response must be a JSON object"
            )
        raw_decisions = payload.get("decisions")
        if not isinstance(raw_decisions, list):
            raise LLMReconciliationParseError("decisions must be a list")
        decisions = [
            self._decision(item)
            for item in raw_decisions
            if isinstance(item, dict)
        ]
        return LLMReconciliationResponse(
            decisions=decisions,
            summary=_string(payload.get("summary")),
            warnings=_string_list(payload.get("warnings")),
            metadata=_dict(payload.get("metadata")),
        )

    def _decision(self, value: dict[str, Any]) -> LLMReconciliationDecision:
        candidate_id = _string(value.get("candidate_id"))
        action = _string(value.get("action"))
        if not candidate_id:
            raise LLMReconciliationParseError("decision missing candidate_id")
        if action not in _ACTIONS:
            raise LLMReconciliationParseError(f"unsupported action: {action!r}")
        confidence = _string(value.get("confidence")) or "medium"
        if confidence not in _CONFIDENCE:
            confidence = "medium"
        return LLMReconciliationDecision(
            candidate_id=candidate_id,
            action=cast(WriteAction, action),
            existing_record_id=_string(value.get("existing_record_id")),
            target_record_id=_string(value.get("target_record_id")),
            target_candidate_id=_string(value.get("target_candidate_id")),
            relation_type=_string(value.get("relation_type")),
            replacement_text=_string(value.get("replacement_text")),
            replacement_metadata=_dict(value.get("replacement_metadata")),
            merge_source_record_ids=_string_list(value.get("merge_source_record_ids")),
            invalidated_record_ids=_string_list(value.get("invalidated_record_ids")),
            confidence=cast(ReconciliationConfidence, confidence),
            reason=_string(value.get("reason")) or "",
            evidence=[
                item for item in _list(value.get("evidence"))
                if isinstance(item, dict)
            ],
            metadata=_dict(value.get("metadata")),
        )


def _load_json_payload(content: str) -> dict[str, Any] | list[Any]:
    text = _extract_json_text(content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as error:
        raise LLMReconciliationParseError(
            "LLM reconciliation response is not valid JSON"
        ) from error
    if not isinstance(payload, (dict, list)):
        raise LLMReconciliationParseError(
            "LLM reconciliation response must be a JSON object or array"
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


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
