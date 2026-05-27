"""Candidate-aware matching for memory reconciliation."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Sequence, cast

from ...models import MemoryRecord, MemoryRecordType, MemorySearchResult

_ASCII_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_CJK_CHUNK_PATTERN = re.compile(r"[\u4e00-\u9fff]+")


@dataclass(frozen=True)
class RelatedMemory:
    """A stored memory record related to one or more extracted candidates."""

    record: MemoryRecord
    score: float
    reasons: list[str] = field(default_factory=list)
    matched_candidate_id: str | None = None
    matched_candidate_type: str | None = None
    match_kind: str = "direct"
    expansion_depth: int = 0

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateRetrievalResult:
    """Candidate-aware retrieval result used before reconciliation."""

    records: list[RelatedMemory] = field(default_factory=list)
    groups: list["CandidateRelatedGroup"] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class CandidateRelatedGroup:
    """Related memories grouped around one extracted candidate."""

    candidate_id: str | None
    candidate_type: str
    candidate_text: str
    direct_matches: list[RelatedMemory] = field(default_factory=list)
    expanded_context: list[RelatedMemory] = field(default_factory=list)

    def to_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass
class _MutableRelated:
    record: MemoryRecord
    score: float
    reasons: set[str]
    matched_candidate_id: str | None
    matched_candidate_type: str | None
    match_kind: str
    expansion_depth: int


@dataclass(frozen=True)
class _RecordIndex:
    records: list[MemoryRecord]
    by_object_key: dict[tuple[str, str], list[MemoryRecord]]
    links: list[MemoryRecord]


class CandidateMemoryMatcher:
    """Match extracted candidates against a prepared memory search result.

    This matcher is intentionally deterministic. It prepares context for a
    future reconciler; it does not deduplicate, merge, or decide writes.
    """

    def __init__(
        self,
        min_score: float = 1.0,
        default_limit: int = 30,
        expand_one_hop: bool = True,
    ) -> None:
        self.min_score = min_score
        self.default_limit = default_limit
        self.expand_one_hop = expand_one_hop

    def match(
        self,
        candidates: Sequence[MemoryRecord],
        search_result: MemorySearchResult,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> CandidateRetrievalResult:
        stored_records = _records_from_search_result(search_result)
        index = self._build_index(stored_records)
        candidate_index = self._build_candidate_index(candidates)
        related: dict[str, _MutableRelated] = {}
        related_by_candidate: dict[str | None, dict[str, _MutableRelated]] = {}

        for candidate in candidates:
            candidate_id = _client_id(candidate) or candidate.id
            candidate_related = related_by_candidate.setdefault(candidate_id, {})
            for record in stored_records:
                score, reasons = self._score_pair(
                    candidate=candidate,
                    record=record,
                    candidate_index=candidate_index,
                    record_index=index,
                )
                if score < self.min_score:
                    continue
                self._add_related(
                    related=related,
                    record=record,
                    score=score,
                    reasons=reasons,
                    matched_candidate=candidate,
                )
                self._add_related(
                    related=candidate_related,
                    record=record,
                    score=score,
                    reasons=reasons,
                    matched_candidate=candidate,
                )

        if self.expand_one_hop:
            self._expand_related_links(related, index)
            for candidate_related in related_by_candidate.values():
                self._expand_related_links(candidate_related, index)

        selected_limit = self.default_limit if limit is None else max(0, limit)
        selected = sorted(
            related.values(),
            key=lambda item: (-item.score, item.record.memory_type, item.record.text),
        )[:selected_limit]
        selected_keys = {_stable_record_key(item.record) for item in selected}
        related_records = [
            self._freeze_related(item)
            for item in selected
        ]
        return CandidateRetrievalResult(
            records=related_records,
            groups=self._build_groups(
                candidates,
                related_by_candidate,
                selected_keys,
            ),
            metadata={
                "matcher": "candidate_rule_based",
                "search": search_result.metadata,
                "candidate_count": len(candidates),
                "stored_record_count": len(stored_records),
                "related_count": len(related),
                "returned_count": len(selected),
                "direct_count": self._match_kind_count(related, "direct"),
                "expanded_count": self._match_kind_count(related, "expanded"),
                "expanded_one_hop": self.expand_one_hop,
            },
        )

    def _freeze_related(self, item: _MutableRelated) -> RelatedMemory:
        return RelatedMemory(
            record=item.record,
            score=round(item.score, 4),
            reasons=sorted(item.reasons),
            matched_candidate_id=item.matched_candidate_id,
            matched_candidate_type=item.matched_candidate_type,
            match_kind=item.match_kind,
            expansion_depth=item.expansion_depth,
        )

    def _build_groups(
        self,
        candidates: Sequence[MemoryRecord],
        related_by_candidate: dict[str | None, dict[str, _MutableRelated]],
        selected_keys: set[str],
    ) -> list[CandidateRelatedGroup]:
        groups: list[CandidateRelatedGroup] = []
        for candidate in candidates:
            candidate_id = _client_id(candidate) or candidate.id
            candidate_related = self._freeze_candidate_related(
                related_by_candidate.get(candidate_id, {}),
                selected_keys,
            )
            groups.append(
                CandidateRelatedGroup(
                    candidate_id=candidate_id,
                    candidate_type=candidate.memory_type,
                    candidate_text=candidate.text,
                    direct_matches=[
                        related for related in candidate_related
                        if related.match_kind == "direct"
                    ],
                    expanded_context=[
                        related for related in candidate_related
                        if related.match_kind == "expanded"
                    ],
                )
            )
        return groups

    def _freeze_candidate_related(
        self,
        related: dict[str, _MutableRelated],
        selected_keys: set[str],
    ) -> list[RelatedMemory]:
        selected = [
            item for item in related.values()
            if _stable_record_key(item.record) in selected_keys
        ]
        return [
            self._freeze_related(item)
            for item in sorted(
                selected,
                key=lambda item: (
                    -item.score,
                    item.record.memory_type,
                    item.record.text,
                ),
            )
        ]

    def _score_pair(
        self,
        candidate: MemoryRecord,
        record: MemoryRecord,
        candidate_index: dict[str, MemoryRecord],
        record_index: _RecordIndex,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        candidate_text = _normalized_text(candidate.text)
        record_text = _normalized_text(record.text)

        if candidate.memory_type == record.memory_type:
            score += 0.15

        if candidate_text and candidate_text == record_text:
            score += 3.0
            reasons.append("text_exact")
        elif candidate_text and record_text and (
            candidate_text in record_text or record_text in candidate_text
        ):
            score += 1.4
            reasons.append("text_contains")

        overlap_score = self._keyword_overlap_score(candidate, record)
        if overlap_score:
            score += overlap_score
            reasons.append(f"keyword_overlap:{overlap_score:.2f}")

        type_score, type_reasons = self._type_specific_score(
            candidate=candidate,
            record=record,
            candidate_index=candidate_index,
            record_index=record_index,
        )
        score += type_score
        reasons.extend(type_reasons)
        return score, reasons

    def _type_specific_score(
        self,
        candidate: MemoryRecord,
        record: MemoryRecord,
        candidate_index: dict[str, MemoryRecord],
        record_index: _RecordIndex,
    ) -> tuple[float, list[str]]:
        if candidate.memory_type == "entity" and record.memory_type == "entity":
            return self._entity_score(candidate, record)
        if candidate.memory_type == "property" and record.memory_type == "property":
            return self._property_score(
                candidate,
                record,
                candidate_index,
                record_index,
            )
        if candidate.memory_type == "event" and record.memory_type == "event":
            return self._event_score(candidate, record)
        if candidate.memory_type == "time_ref" and record.memory_type == "time_ref":
            return self._time_score(candidate, record)
        return 0.0, []

    def _entity_score(
        self,
        candidate: MemoryRecord,
        record: MemoryRecord,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        candidate_name = _normalized_text(candidate.text)
        aliases = _metadata_strings(record, "aliases")
        if candidate_name and candidate_name in {_normalized_text(alias) for alias in aliases}:
            score += 2.5
            reasons.append("entity_alias_exact")
        if _metadata_text_contains(record, "identity_summary", candidate.text):
            score += 1.0
            reasons.append("entity_identity_summary_contains")
        if candidate.metadata.get("entity_type") == record.metadata.get("entity_type"):
            score += 0.25
        return score, reasons

    def _property_score(
        self,
        candidate: MemoryRecord,
        record: MemoryRecord,
        candidate_index: dict[str, MemoryRecord],
        record_index: _RecordIndex,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        if candidate.metadata.get("property_type") == record.metadata.get("property_type"):
            score += 0.25

        candidate_entity = self._linked_entity_text(candidate, candidate_index)
        record_entity = self._linked_entity_text(record, record_index.by_object_key)
        if candidate_entity and record_entity:
            if _normalized_text(candidate_entity) == _normalized_text(record_entity):
                score += 2.0
                reasons.append("property_entity_exact")
            elif _shared_tokens(candidate_entity, record_entity):
                score += 0.8
                reasons.append("property_entity_overlap")
        return score, reasons

    def _event_score(
        self,
        candidate: MemoryRecord,
        record: MemoryRecord,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        if candidate.metadata.get("event_type") == record.metadata.get("event_type"):
            score += 0.25
        summary_score = _token_overlap_score(
            _search_text(candidate, extra_keys=("summary",)),
            _search_text(record, extra_keys=("summary",)),
        )
        if summary_score:
            score += summary_score
            reasons.append(f"event_summary_overlap:{summary_score:.2f}")
        return score, reasons

    def _time_score(
        self,
        candidate: MemoryRecord,
        record: MemoryRecord,
    ) -> tuple[float, list[str]]:
        score = 0.0
        reasons: list[str] = []
        for field_name in ("raw_text", "resolved_start", "resolved_end"):
            candidate_value = _normalized_text(str(candidate.metadata.get(field_name, "")))
            record_value = _normalized_text(str(record.metadata.get(field_name, "")))
            if candidate_value and candidate_value == record_value:
                score += 2.0
                reasons.append(f"time_{field_name}_exact")
        if candidate.metadata.get("time_kind") == record.metadata.get("time_kind"):
            score += 0.2
        if candidate.metadata.get("timeline_kind") == record.metadata.get("timeline_kind"):
            score += 0.2
        return score, reasons

    def _keyword_overlap_score(
        self,
        candidate: MemoryRecord,
        record: MemoryRecord,
    ) -> float:
        return _token_overlap_score(_search_text(candidate), _search_text(record))

    def _expand_related_links(
        self,
        related: dict[str, _MutableRelated],
        index: _RecordIndex,
    ) -> None:
        direct_matches = [
            item for item in related.values()
            if item.match_kind == "direct"
        ]
        for item in direct_matches:
            for link in index.links:
                endpoints = list(self._link_endpoints(link))
                touched = [
                    endpoint for endpoint in endpoints
                    if self._record_has_object_key(item.record, endpoint)
                ]
                if not touched or not _sources_overlap(item.record, link):
                    continue
                self._add_expanded_record(
                    related,
                    link,
                    item,
                    reason=self._link_reason(link),
                )
                for endpoint in endpoints:
                    if endpoint in touched:
                        continue
                    for neighbor in self._resolve_endpoint(endpoint, link, index):
                        self._add_expanded_record(
                            related,
                            neighbor,
                            item,
                            reason=f"one_hop_neighbor:{self._link_reason(link)}",
                        )

    def _add_expanded_record(
        self,
        related: dict[str, _MutableRelated],
        record: MemoryRecord,
        origin: _MutableRelated,
        reason: str,
    ) -> None:
        self._add_related(
            related=related,
            record=record,
            score=max(origin.score * 0.72, self.min_score),
            reasons=[reason],
            matched_candidate_id=origin.matched_candidate_id,
            matched_candidate_type=origin.matched_candidate_type,
            match_kind="expanded",
            expansion_depth=1,
        )

    def _add_related(
        self,
        related: dict[str, _MutableRelated],
        record: MemoryRecord,
        score: float,
        reasons: list[str],
        matched_candidate: MemoryRecord | None = None,
        matched_candidate_id: str | None = None,
        matched_candidate_type: str | None = None,
        match_kind: str = "direct",
        expansion_depth: int = 0,
    ) -> None:
        key = _stable_record_key(record)
        candidate_id = matched_candidate_id
        candidate_type = matched_candidate_type
        if matched_candidate:
            candidate_id = _client_id(matched_candidate) or matched_candidate.id
            candidate_type = matched_candidate.memory_type

        existing = related.get(key)
        if existing is None:
            related[key] = _MutableRelated(
                record=record,
                score=score,
                reasons=set(reasons),
                matched_candidate_id=candidate_id,
                matched_candidate_type=candidate_type,
                match_kind=match_kind,
                expansion_depth=expansion_depth,
            )
            return

        existing.score = max(existing.score, score)
        existing.reasons.update(reasons)
        if existing.match_kind != "direct" and match_kind == "direct":
            existing.match_kind = "direct"
            existing.expansion_depth = 0
        elif existing.match_kind == match_kind:
            existing.expansion_depth = min(existing.expansion_depth, expansion_depth)
        if existing.matched_candidate_id is None:
            existing.matched_candidate_id = candidate_id
        if existing.matched_candidate_type is None:
            existing.matched_candidate_type = candidate_type

    def _match_kind_count(
        self,
        related: dict[str, _MutableRelated],
        match_kind: str,
    ) -> int:
        return sum(1 for item in related.values() if item.match_kind == match_kind)

    def _build_index(self, records: Sequence[MemoryRecord]) -> _RecordIndex:
        by_object_key: dict[tuple[str, str], list[MemoryRecord]] = {}
        links: list[MemoryRecord] = []
        for record in records:
            for object_key in _object_keys(record):
                by_object_key.setdefault(object_key, []).append(record)
            if record.memory_type in {"link", "time_link"}:
                links.append(record)
        return _RecordIndex(list(records), by_object_key, links)

    def _build_candidate_index(
        self,
        candidates: Sequence[MemoryRecord],
    ) -> dict[str, MemoryRecord]:
        index: dict[str, MemoryRecord] = {}
        for candidate in candidates:
            client_id = _client_id(candidate)
            if client_id:
                index[client_id] = candidate
        return index

    def _linked_entity_text(
        self,
        record: MemoryRecord,
        index: dict[str, MemoryRecord] | dict[tuple[str, str], list[MemoryRecord]],
    ) -> str | None:
        entity_client_id = record.metadata.get("entity_client_id")
        if not isinstance(entity_client_id, str):
            return None
        if entity_client_id in index:
            candidate = index[entity_client_id]  # type: ignore[index]
            if isinstance(candidate, MemoryRecord):
                return candidate.text
        records = index.get(("entity", entity_client_id), [])  # type: ignore[arg-type]
        if records:
            return records[0].text
        return None

    def _link_endpoints(self, link: MemoryRecord) -> Iterable[tuple[str, str]]:
        if link.memory_type == "link":
            from_type = link.metadata.get("from_type")
            from_client_id = link.metadata.get("from_client_id")
            to_type = link.metadata.get("to_type")
            to_client_id = link.metadata.get("to_client_id")
            if isinstance(from_type, str) and isinstance(from_client_id, str):
                yield (from_type, from_client_id)
            if isinstance(to_type, str) and isinstance(to_client_id, str):
                yield (to_type, to_client_id)
        if link.memory_type == "time_link":
            target_type = link.metadata.get("target_type")
            target_client_id = link.metadata.get("target_client_id")
            time_ref_client_id = link.metadata.get("time_ref_client_id")
            if isinstance(target_type, str) and isinstance(target_client_id, str):
                yield (target_type, target_client_id)
            if isinstance(time_ref_client_id, str):
                yield ("time_ref", time_ref_client_id)

    def _record_has_object_key(
        self,
        record: MemoryRecord,
        object_key: tuple[str, str],
    ) -> bool:
        return object_key in set(_object_keys(record))

    def _resolve_endpoint(
        self,
        endpoint: tuple[str, str],
        link: MemoryRecord,
        index: _RecordIndex,
    ) -> list[MemoryRecord]:
        records = index.by_object_key.get(endpoint, [])
        with_shared_source = [
            record for record in records if _sources_overlap(record, link)
        ]
        return with_shared_source or records[:1]

    def _link_reason(self, link: MemoryRecord) -> str:
        if link.memory_type == "time_link":
            role = link.metadata.get("time_role")
            return f"time_link:{role}" if isinstance(role, str) else "time_link"
        relation = link.metadata.get("relation_type")
        return f"link:{relation}" if isinstance(relation, str) else "link"


def _client_id(record: MemoryRecord) -> str | None:
    value = record.metadata.get("candidate_client_id")
    return value if isinstance(value, str) and value else None


def _records_from_search_result(search_result: MemorySearchResult) -> list[MemoryRecord]:
    records: list[MemoryRecord] = []
    seen: set[str] = set()
    for hit in search_result.hits:
        record = hit.record or _record_from_hit(hit)
        if record is None:
            continue
        key = _stable_record_key(record)
        if key in seen:
            continue
        records.append(record)
        seen.add(key)
    return records


def _record_from_hit(hit) -> MemoryRecord | None:
    object_type = hit.object_ref.object_type
    if object_type not in {
        "event",
        "description",
        "entity",
        "property",
        "link",
        "time_ref",
        "time_link",
        "summary",
    }:
        return None
    return MemoryRecord(
        id=hit.object_ref.object_id,
        memory_type=cast(MemoryRecordType, object_type),
        text=hit.matched_text or hit.object_ref.object_id,
        metadata={
            **dict(hit.metadata),
            "search_reason": hit.reason,
            "search_score": hit.score,
        },
    )


def _stable_record_key(record: MemoryRecord) -> str:
    if record.id:
        return f"id:{record.id}"
    client_id = _client_id(record)
    if client_id:
        return f"client:{record.memory_type}:{client_id}:{record.text}"
    return f"value:{record.memory_type}:{record.text}:{id(record)}"


def _object_keys(record: MemoryRecord) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    if record.id:
        keys.append((record.memory_type, record.id))
    client_id = _client_id(record)
    if client_id:
        keys.append((record.memory_type, client_id))
    return keys


def _normalized_text(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _metadata_strings(record: MemoryRecord, key: str) -> list[str]:
    value = record.metadata.get(key)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _metadata_text_contains(record: MemoryRecord, key: str, needle: str) -> bool:
    value = record.metadata.get(key)
    if not isinstance(value, str):
        return False
    return _normalized_text(needle) in _normalized_text(value)


def _search_text(
    record: MemoryRecord,
    extra_keys: tuple[str, ...] = ("identity_summary", "summary", "raw_text"),
) -> str:
    parts = [record.text]
    for key in extra_keys:
        value = record.metadata.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(item for item in value if isinstance(item, str))
    return " ".join(parts)


def _token_overlap_score(left: str, right: str) -> float:
    shared = _shared_tokens(left, right)
    if not shared:
        return 0.0
    return min(1.4, len(shared) * 0.28)


def _shared_tokens(left: str, right: str) -> set[str]:
    return _tokens(left) & _tokens(right)


def _tokens(text: str) -> set[str]:
    normalized = _normalized_text(text)
    tokens = set(_ASCII_TOKEN_PATTERN.findall(normalized))
    for chunk in _CJK_CHUNK_PATTERN.findall(normalized):
        if len(chunk) <= 2:
            tokens.add(chunk)
            continue
        tokens.add(chunk)
        tokens.update(chunk[index : index + 2] for index in range(len(chunk) - 1))
        tokens.update(chunk[index : index + 3] for index in range(len(chunk) - 2))
    return {token for token in tokens if len(token) >= 2}


def _source_ids(record: MemoryRecord) -> set[str]:
    return {
        source.source_id
        for source in record.source_refs
        if source.source_id
    }


def _sources_overlap(left: MemoryRecord, right: MemoryRecord) -> bool:
    left_sources = _source_ids(left)
    right_sources = _source_ids(right)
    if not left_sources or not right_sources:
        return True
    return bool(left_sources & right_sources)
