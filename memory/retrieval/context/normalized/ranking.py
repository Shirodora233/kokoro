"""Ranking rules for normalized memory search hits."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from ....models import MemorySearchHit, MemorySearchRequest


class NormalizedMemoryRanker:
    """Score normalized search hits before hydration.

    The ranker keeps search implementations focused on recall. It centralizes
    ranking rules that affect which event/entity views are eventually rendered
    into prompt context.
    """

    def __init__(self, now: datetime | None = None) -> None:
        self.now = now

    def rank(
        self,
        hits: Sequence[MemorySearchHit],
        request: MemorySearchRequest,
    ) -> list[MemorySearchHit]:
        if not hits:
            return []
        # Normalize base scores to [0, 1] so ranker bonuses are consistent
        # regardless of score source (lexical 0.85-1.30 vs RRF 0.016-0.032).
        base_min = min(hit.score for hit in hits)
        base_max = max(hit.score for hit in hits)
        base_range = base_max - base_min or 1.0

        def _normalize(raw: float) -> float:
            return (raw - base_min) / base_range

        ranked = [
            self._rank_hit(hit, request, _normalize(hit.score))
            for hit in hits
        ]
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
        hit: MemorySearchHit,
        request: MemorySearchRequest,
        normalized_base: float,
    ) -> MemorySearchHit:
        metadata = dict(hit.metadata)
        components = {
            "base": round(normalized_base, 4),
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
    hits: Sequence[MemorySearchHit],
) -> list[MemorySearchHit]:
    selected: dict[tuple[str, str], MemorySearchHit] = {}
    for hit in hits:
        key = (hit.object_ref.object_type, hit.object_ref.object_id)
        previous = selected.get(key)
        if previous is None or hit.score > previous.score:
            selected[key] = hit
    return list(selected.values())


def _match_quality_bonus(value: object) -> float:
    if value == "exact":
        return 0.06
    if value == "phrase":
        return 0.04
    if value == "all_terms":
        return 0.02
    if value == "semantic":
        return 0.01
    if value == "term":
        return 0.005
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
        return 0.04
    if request_user_id and hit_user_id == request_user_id:
        return 0.02
    if hit_user_id is None and hit_session_id is None:
        return 0.01
    return 0.0


def _importance_bonus(value: object) -> float:
    if value == "high":
        return 0.03
    if value == "medium":
        return 0.01
    return 0.0


def _confidence_bonus(value: object) -> float:
    if value == "high":
        return 0.02
    if value == "medium":
        return 0.005
    return 0.0


def _recency_bonus(value: object, now: datetime) -> float:
    updated_at = _parse_datetime(value)
    if updated_at is None:
        return 0.0
    age_days = max(0.0, (now - updated_at).total_seconds() / 86400)
    if age_days <= 1:
        return 0.03
    if age_days <= 7:
        return 0.015
    if age_days <= 30:
        return 0.005
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
