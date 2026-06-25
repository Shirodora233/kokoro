"""Repository interfaces for durable memory persistence."""

from __future__ import annotations

from typing import Protocol, Sequence

from ..models import MemoryRecord
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

    def get_record_as_of(
        self,
        record_id: str,
        checkpoint_id: str | None,
    ) -> MemoryRecord | None:
        """Load one generic memory record as visible at a checkpoint."""

    def get_event(
        self,
        event_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentEvent | None:
        """Load one event by id."""

    def get_description(
        self,
        description_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentDescription | None:
        """Load one description by id."""

    def get_entity(
        self,
        entity_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentEntity | None:
        """Load one entity by id."""

    def get_property(
        self,
        property_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentProperty | None:
        """Load one property by id."""

    def get_link(
        self,
        link_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentLink | None:
        """Load one link by id."""

    def get_time_ref(
        self,
        time_ref_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentTimeRef | None:
        """Load one semantic time reference by id."""

    def get_time_link(
        self,
        time_link_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentTimeLink | None:
        """Load one semantic time link by id."""

    def list_events(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentEvent]:
        """List active events by scope."""

    def list_entities(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentEntity]:
        """List entities by scope."""

    def list_descriptions(
        self,
        event_ids: Sequence[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentDescription]:
        """List active descriptions by parent event or scope."""

    def list_properties(
        self,
        entity_ids: Sequence[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentProperty]:
        """List active properties by parent entity or scope."""

    def list_links(
        self,
        object_refs: Sequence[PersistentObjectRef] | None = None,
        user_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentLink]:
        """List active links touching the given objects."""

    def list_time_links(
        self,
        target_refs: Sequence[PersistentObjectRef] | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentTimeLink]:
        """List time links for the given target objects."""

    def list_time_refs(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentTimeRef]:
        """List active semantic time references by scope."""

    def get_time_refs(
        self,
        time_ref_ids: Sequence[str],
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentTimeRef]:
        """Load semantic time references by id."""

    def list_records_as_of(
        self,
        checkpoint_id: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        """List generic memory records as visible at a checkpoint."""
