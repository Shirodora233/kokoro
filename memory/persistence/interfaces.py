"""Repository interfaces for durable memory persistence."""

from __future__ import annotations

from typing import Protocol

from .models import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentMemoryBundle,
    PersistentProperty,
    PersistentTimeLink,
    PersistentTimeRef,
)


class PersistentMemoryRepository(Protocol):
    """Persistence boundary for normalized durable memory objects."""

    def save_bundle(self, bundle: PersistentMemoryBundle) -> PersistentMemoryBundle:
        """Persist a normalized memory bundle and return stored objects."""

    def get_event(self, event_id: str) -> PersistentEvent | None:
        """Load one event by id."""

    def get_description(self, description_id: str) -> PersistentDescription | None:
        """Load one description by id."""

    def get_entity(self, entity_id: str) -> PersistentEntity | None:
        """Load one entity by id."""

    def get_property(self, property_id: str) -> PersistentProperty | None:
        """Load one property by id."""

    def get_link(self, link_id: str) -> PersistentLink | None:
        """Load one link by id."""

    def get_time_ref(self, time_ref_id: str) -> PersistentTimeRef | None:
        """Load one semantic time reference by id."""

    def get_time_link(self, time_link_id: str) -> PersistentTimeLink | None:
        """Load one semantic time link by id."""

    def list_events(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentEvent]:
        """List active events by scope."""

    def list_entities(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentEntity]:
        """List entities by scope."""
