"""Ranking rules for normalized memory lookup hits."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from .lookup import NormalizedMemoryLookupHit, NormalizedMemoryLookupRequest


class NormalizedMemoryRanker:
    """Score normalized lookup hits before hydration.

    The ranker keeps lookup implementations focused on recall. It centralizes
    ranking rules that affect which event/entity views are eventually rendered
    into prompt context.
    """

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now

    def rank(
        self,
        hits: Sequence[NormalizedMemoryLookupHit],
        request: NormalizedMemoryLookupRequest,
    ) -> list[NormalizedMemoryLookupHit]:
        ranked = [self._rank_hit(hit, request) for hit in hits]
        deduped = _dedupe_best_hit(ranked)
        return sorted(
            deduped,
            key=lambda hit: (
                hit.score,
                str(hit.metadata.get("updated_at", "")),
            ),
            reverse=True,
        )

    def _rank_hit(
        self,
        hit: NormalizedMemoryLookupHit,
        request: NormalizedMemoryLookupRequest,
    ) -> NormalizedMemoryLookupHit:
        metadata = dict(hit.metadata)
        components = {
            "base": hit.score,
            "match_quality": _match_quality_bonus(metadata.get("match_quality")),
            "scope": _scope_bonus(
                request_user_id=request.user_id,
                request_session_id=request.session_id,
                hit_user_id=_metadata_string(metadata, "user_id"),
                hit_session_id=_metadata_string(metadata, "session_id"),
            ),
            "importance": _importance_bonus(metadata.get("importance")),
            "confidence": _confidence_bonus(metadata.get("confidence")),
            "recency": _recency_bonus(
                metadata.get("updated_at"),
                now=self.now or datetime.now(timezone.utc),
            ),
        }
        final_score = round(sum(components.values()), 4)
        metadata["ranking"] = {
            "final_score": final_score,
            "components": components,
        }
        return replace(hit, score=final_score, metadata=metadata)


def _dedupe_best_hit(
    hits: Sequence[NormalizedMemoryLookupHit],
) -> list[NormalizedMemoryLookupHit]:
    selected: dict[tuple[str, str], NormalizedMemoryLookupHit] = {}
    for hit in hits:
        key = (hit.object_ref.object_type, hit.object_ref.object_id)
        previous = selected.get(key)
        if previous is None or hit.score > previous.score:
            selected[key] = hit
    return list(selected.values())


def _match_quality_bonus(value: object) -> float:
    if value == "exact":
        return 0.3
    if value == "phrase":
        return 0.18
    if value == "all_terms":
        return 0.1
    if value == "term":
        return 0.04
    if value == "recent":
        return 0.0
    return 0.0


def _scope_bonus(
    request_user_id: str | None,
    request_session_id: str | None,
    hit_user_id: str | None,
    hit_session_id: str | None,
) -> float:
    if request_session_id and hit_session_id == request_session_id:
        return 0.2
    if request_user_id and hit_user_id == request_user_id:
        return 0.12
    if hit_user_id is None and hit_session_id is None:
        return 0.04
    return 0.0


def _importance_bonus(value: object) -> float:
    if value == "high":
        return 0.08
    if value == "medium":
        return 0.03
    return 0.0


def _confidence_bonus(value: object) -> float:
    if value == "high":
        return 0.05
    if value == "medium":
        return 0.02
    return 0.0


def _recency_bonus(value: object, now: datetime) -> float:
    updated_at = _parse_datetime(value)
    if updated_at is None:
        return 0.0
    age_days = max(0.0, (now - updated_at).total_seconds() / 86400)
    if age_days <= 1:
        return 0.08
    if age_days <= 7:
        return 0.05
    if age_days <= 30:
        return 0.02
    return 0.0


def _parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None
