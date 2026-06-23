"""Repository interfaces for durable memory persistence."""

from __future__ import annotations

from typing import Any, Mapping, Protocol, Sequence

from .models import (
    PersistentObjectRef,
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

    def update_object_status(
        self,
        object_id: str,
        status: str,
        *,
        merged_into_object_id: str | None = None,
        deleted_reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Update shared memory object lifecycle fields."""

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

    def list_descriptions(
        self,
        event_ids: Sequence[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        visible_session_scopes: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[PersistentDescription]:
        """List active descriptions by parent event or scope."""

    def list_properties(
        self,
        entity_ids: Sequence[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        visible_session_scopes: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[PersistentProperty]:
        """List active properties by parent entity or scope."""

    def list_links(
        self,
        object_refs: Sequence[PersistentObjectRef] | None = None,
        user_id: str | None = None,
        limit: int | None = None,
        session_id: str | None = None,
        visible_session_scopes: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[PersistentLink]:
        """List active links touching the given objects."""

    def list_time_links(
        self,
        target_refs: Sequence[PersistentObjectRef] | None = None,
        limit: int | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        visible_session_scopes: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[PersistentTimeLink]:
        """List time links for the given target objects."""

    def get_time_refs(
        self,
        time_ref_ids: Sequence[str],
    ) -> list[PersistentTimeRef]:
        """Load semantic time references by id."""

    def tombstone_by_session_id(
        self,
        session_id: str,
        *,
        deleted_reason: str = "session_deleted",
    ) -> int:
        """Soft-delete (tombstone) all active memory objects for a session.

        Returns count of objects tombstoned.
        """

    def tombstone_by_user_id(
        self,
        user_id: str,
        *,
        deleted_reason: str = "user_deleted",
    ) -> int:
        """Soft-delete (tombstone) all active memory objects for a user.

        Returns count of objects tombstoned.
        """

    def delete_all_memory(self) -> dict[str, int]:
        """Hard-delete all memory objects, embeddings, and source refs."""
