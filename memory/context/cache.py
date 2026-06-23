"""Process-local active memory context cache."""

from __future__ import annotations

import time as _time
from dataclasses import replace
from threading import RLock
from typing import Iterable

from ..models import ActiveMemoryContext, MemoryRecord

_ContextKey = tuple[str | None, str | None]


class InMemoryActiveMemoryCache:
    """Keep recently used memories for each user/session pair."""

    def __init__(
        self,
        max_event_memories: int = 8,
        max_entity_memories: int = 16,
        max_property_memories: int = 16,
        max_other_memories: int = 16,
    ) -> None:
        self.max_event_memories = max_event_memories
        self.max_entity_memories = max_entity_memories
        self.max_property_memories = max_property_memories
        self.max_other_memories = max_other_memories
        self._contexts: dict[_ContextKey, ActiveMemoryContext] = {}
        self._lock = RLock()

    def get(
        self,
        user_id: str | None,
        session_id: str | None,
    ) -> ActiveMemoryContext:
        with self._lock:
            return self._contexts.get((user_id, session_id), ActiveMemoryContext())

    def set(
        self,
        user_id: str | None,
        session_id: str | None,
        context: ActiveMemoryContext,
    ) -> ActiveMemoryContext:
        trimmed = self._trim(context)
        with self._lock:
            self._contexts[(user_id, session_id)] = trimmed
        return trimmed

    def refresh(
        self,
        user_id: str | None,
        session_id: str | None,
        new_message_id: str | None,
        active_context: ActiveMemoryContext | None = None,
        memories: Iterable[MemoryRecord] = (),
    ) -> ActiveMemoryContext:
        current = active_context or self.get(user_id=user_id, session_id=session_id)
        incoming = list(memories)
        updated = replace(
            current,
            event_memories=self._merge_front(
                current.event_memories,
                [record for record in incoming if record.memory_type == "event"],
                self.max_event_memories,
            ),
            entity_memories=self._merge_front(
                current.entity_memories,
                [record for record in incoming if record.memory_type == "entity"],
                self.max_entity_memories,
            ),
            property_memories=self._merge_front(
                current.property_memories,
                [record for record in incoming if record.memory_type == "property"],
                self.max_property_memories,
            ),
            other_memories=self._merge_front(
                current.other_memories,
                [
                    record
                    for record in incoming
                    if record.memory_type not in {"event", "entity", "property"}
                ],
                self.max_other_memories,
            ),
            last_refreshed_at_message_id=new_message_id,
            last_refreshed_at_ts=_time.time(),
        )
        return self.set(user_id=user_id, session_id=session_id, context=updated)

    def clear(self) -> None:
        with self._lock:
            self._contexts.clear()

    def remove(
        self,
        user_id: str | None,
        session_id: str | None,
    ) -> None:
        """Remove the active context entry for one user/session pair."""
        with self._lock:
            self._contexts.pop((user_id, session_id), None)

    def remove_by_user_id(self, user_id: str) -> None:
        """Remove all active context entries for a given user."""
        with self._lock:
            keys_to_remove = [
                key for key in self._contexts if key[0] == user_id
            ]
            for key in keys_to_remove:
                self._contexts.pop(key, None)

    # ----------------------------------------------------------------
    # TTL and decay
    # ----------------------------------------------------------------

    def evict_record_id(self, record_id: str) -> int:
        """Remove a record by id from all active context entries.

        Returns the number of entries modified.
        """
        count = 0
        with self._lock:
            for key, context in list(self._contexts.items()):
                new_context = _remove_record_from_context(context, record_id)
                if new_context is not context:
                    self._contexts[key] = new_context
                    count += 1
        return count

    def expire_stale_contexts(
        self,
        max_age_seconds: float = 3600.0,
        now: float | None = None,
    ) -> int:
        """Remove context entries older than max_age_seconds.

        Returns the number of entries removed.
        """
        current = now or _time.time()
        expired_keys: list[_ContextKey] = []
        with self._lock:
            for key, context in self._contexts.items():
                if _context_age_seconds(context, current) > max_age_seconds:
                    expired_keys.append(key)
            for key in expired_keys:
                self._contexts.pop(key, None)
        return len(expired_keys)

    def _trim(self, context: ActiveMemoryContext) -> ActiveMemoryContext:
        return replace(
            context,
            event_memories=context.event_memories[: self.max_event_memories],
            entity_memories=context.entity_memories[: self.max_entity_memories],
            property_memories=context.property_memories[: self.max_property_memories],
            other_memories=context.other_memories[: self.max_other_memories],
        )

    def _merge_front(
        self,
        current: list[MemoryRecord],
        incoming: list[MemoryRecord],
        limit: int,
    ) -> list[MemoryRecord]:
        merged: list[MemoryRecord] = []
        seen: set[str] = set()

        for record in [*incoming, *current]:
            key = record.id or f"{record.memory_type}:{record.text}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(record)
            if len(merged) >= limit:
                break
        return merged


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _remove_record_from_context(
    context: ActiveMemoryContext,
    record_id: str,
) -> ActiveMemoryContext:
    """Return a new context with the given record id removed from all lists."""
    changed = False
    for attr in ("event_memories", "entity_memories", "property_memories", "other_memories"):
        records = getattr(context, attr)
        filtered = [r for r in records if r.id != record_id]
        if len(filtered) != len(records):
            context = replace(context, **{attr: filtered})
            changed = True
    if changed:
        context = replace(context, metadata=dict(context.metadata))
    return context


def _context_age_seconds(context: ActiveMemoryContext, now: float) -> float:
    """Return age of the context's last refresh in seconds."""
    ts = context.last_refreshed_at_ts
    return now - ts if ts > 0 else 0.0
