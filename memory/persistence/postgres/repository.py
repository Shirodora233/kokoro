"""PostgreSQL repository for normalized durable memory objects."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from psycopg.types.json import Jsonb

from ...models import MemoryRecord, MemorySourceRef
from ..interfaces import PersistentMemoryRepository
from ..models import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentMemoryBundle,
    PersistentObjectRef,
    PersistentProperty,
    PersistentSourceRef,
    PersistentTimeLink,
    PersistentTimeRef,
)
from .connection import PostgresPersistentMemoryDatabase
from .ids import new_persistent_id
from .row_mappers import (
    description_from_row,
    entity_from_row,
    event_from_row,
    link_from_row,
    property_from_row,
    time_link_from_row,
    time_ref_from_row,
)
from .source_repository import PostgresMemorySourceRepository


class PostgresPersistentMemoryRepository(PersistentMemoryRepository):
    """Repository for normalized memory tables backed by memory_objects."""

    def __init__(
        self,
        database_url: str | None = None,
        database: PostgresPersistentMemoryDatabase | None = None,
        ensure_schema: bool = True,
    ) -> None:
        if database is None:
            if database_url is None:
                raise ValueError("database_url is required")
            database = PostgresPersistentMemoryDatabase(database_url)
        self.database = database
        self.sources = PostgresMemorySourceRepository()
        if ensure_schema:
            self.ensure_schema()

    def ensure_schema(self) -> None:
        self.database.ensure_schema()

    def save_bundle(self, bundle: PersistentMemoryBundle) -> PersistentMemoryBundle:
        with self.database.connect() as connection:
            return self.save_bundle_in_connection(connection, bundle)

    def save_bundle_in_connection(
        self,
        connection: Any,
        bundle: PersistentMemoryBundle,
    ) -> PersistentMemoryBundle:
        events = [self._save_event(connection, event) for event in bundle.events]
        entities = [self._save_entity(connection, entity) for entity in bundle.entities]
        time_refs = [
            self._save_time_ref(connection, time_ref)
            for time_ref in bundle.time_refs
        ]
        descriptions = [
            self._save_description(connection, description)
            for description in bundle.descriptions
        ]
        properties = [
            self._save_property(connection, memory_property)
            for memory_property in bundle.properties
        ]
        links = [self._save_link(connection, link) for link in bundle.links]
        time_links = [
            self._save_time_link(connection, time_link)
            for time_link in bundle.time_links
        ]
        return PersistentMemoryBundle(
            events=events,
            descriptions=descriptions,
            entities=entities,
            properties=properties,
            links=links,
            time_refs=time_refs,
            time_links=time_links,
            metadata=dict(bundle.metadata),
        )

    def update_object_status(
        self,
        object_id: str,
        status: str,
        *,
        merged_into_object_id: str | None = None,
        deleted_reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        with self.database.connect() as connection:
            self.update_object_status_in_connection(
                connection,
                object_id,
                status,
                merged_into_object_id=merged_into_object_id,
                deleted_reason=deleted_reason,
                metadata=metadata,
            )

    def update_object_status_in_connection(
        self,
        connection: Any,
        object_id: str,
        status: str,
        *,
        merged_into_object_id: str | None = None,
        deleted_reason: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        row = connection.execute(
            "SELECT * FROM memory_objects WHERE id = %s",
            (object_id,),
        ).fetchone()
        if not row:
            return
        revision_metadata = {**dict(row["metadata"] or {}), **dict(metadata or {})}
        payload, source_refs = self._latest_revision_payload(connection, object_id)
        connection.execute(
            """
            UPDATE memory_objects
            SET status = %s,
                merged_into_object_id = %s,
                deleted_reason = COALESCE(%s, deleted_reason),
                metadata = metadata || %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                status,
                merged_into_object_id,
                deleted_reason,
                Jsonb(dict(metadata or {})),
                object_id,
            ),
        )
        self._save_revision(
            connection,
            object_id=object_id,
            checkpoint_id=_metadata_string(revision_metadata, "created_checkpoint_id"),
            turn_id=_metadata_string(revision_metadata, "created_turn_id"),
            operation=_revision_operation(revision_metadata.get("write_action")),
            status_after=status,
            confidence=row["confidence"],
            importance=row["importance"],
            payload=payload,
            source_refs=source_refs,
            metadata=revision_metadata,
            merged_into_object_id=merged_into_object_id,
        )

    def get_record_as_of(
        self,
        record_id: str,
        checkpoint_id: str | None,
    ) -> MemoryRecord | None:
        if checkpoint_id is None:
            return _persistent_to_record(self._get_current_any(record_id))
        with self.database.connect() as connection:
            item = self._persistent_as_of(connection, record_id, checkpoint_id)
        return _persistent_to_record(item)

    def get_event(
        self,
        event_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentEvent | None:
        if as_of_checkpoint_id is not None:
            with self.database.connect() as connection:
                item = self._persistent_as_of(connection, event_id, as_of_checkpoint_id)
            return item if isinstance(item, PersistentEvent) else None
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_EVENT_SELECT} WHERE e.id = %s",
                (event_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, event_id)
        return event_from_row(row, source_refs)

    def get_description(
        self,
        description_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentDescription | None:
        if as_of_checkpoint_id is not None:
            with self.database.connect() as connection:
                item = self._persistent_as_of(
                    connection,
                    description_id,
                    as_of_checkpoint_id,
                )
            return item if isinstance(item, PersistentDescription) else None
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_DESCRIPTION_SELECT} WHERE d.id = %s",
                (description_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, description_id)
        return description_from_row(row, source_refs)

    def get_entity(
        self,
        entity_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentEntity | None:
        if as_of_checkpoint_id is not None:
            with self.database.connect() as connection:
                item = self._persistent_as_of(connection, entity_id, as_of_checkpoint_id)
            return item if isinstance(item, PersistentEntity) else None
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_ENTITY_SELECT} WHERE ent.id = %s GROUP BY ent.id, o.id, cp.sequence",
                (entity_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, entity_id)
        return entity_from_row(row, source_refs)

    def get_property(
        self,
        property_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentProperty | None:
        if as_of_checkpoint_id is not None:
            with self.database.connect() as connection:
                item = self._persistent_as_of(
                    connection,
                    property_id,
                    as_of_checkpoint_id,
                )
            return item if isinstance(item, PersistentProperty) else None
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_PROPERTY_SELECT} WHERE p.id = %s",
                (property_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, property_id)
        return property_from_row(row, source_refs)

    def get_link(
        self,
        link_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentLink | None:
        if as_of_checkpoint_id is not None:
            with self.database.connect() as connection:
                item = self._persistent_as_of(connection, link_id, as_of_checkpoint_id)
            if not isinstance(item, PersistentLink):
                return None
            return item if self._link_endpoints_visible(item, as_of_checkpoint_id) else None
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_RELATION_SELECT} WHERE r.id = %s",
                (link_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, link_id)
        return link_from_row(row, source_refs)

    def get_time_ref(
        self,
        time_ref_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentTimeRef | None:
        if as_of_checkpoint_id is not None:
            with self.database.connect() as connection:
                item = self._persistent_as_of(
                    connection,
                    time_ref_id,
                    as_of_checkpoint_id,
                )
            return item if isinstance(item, PersistentTimeRef) else None
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_TIME_REF_SELECT} WHERE tr.id = %s",
                (time_ref_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, time_ref_id)
        return time_ref_from_row(row, source_refs)

    def get_time_link(
        self,
        time_link_id: str,
        as_of_checkpoint_id: str | None = None,
    ) -> PersistentTimeLink | None:
        if as_of_checkpoint_id is not None:
            with self.database.connect() as connection:
                item = self._persistent_as_of(
                    connection,
                    time_link_id,
                    as_of_checkpoint_id,
                )
            if not isinstance(item, PersistentTimeLink):
                return None
            return item if self._time_link_endpoints_visible(
                item,
                as_of_checkpoint_id,
            ) else None
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_TIME_LINK_SELECT} WHERE tl.id = %s",
                (time_link_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, time_link_id)
        return time_link_from_row(row, source_refs)

    def list_events(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentEvent]:
        if as_of_checkpoint_id is not None:
            items = self._list_persistent_as_of(
                as_of_checkpoint_id,
                "event",
                user_id=user_id,
                session_id=session_id,
                limit=limit,
            )
            return [item for item in items if isinstance(item, PersistentEvent)]
        conditions, params = _object_scope_conditions(user_id, session_id)
        conditions.insert(0, "o.status = 'active'")
        query = (
            f"{_EVENT_SELECT} WHERE {' AND '.join(conditions)} "
            "ORDER BY o.updated_at DESC, e.id ASC"
        )
        query, params = _with_limit(query, params, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                event_from_row(
                    row,
                    self.sources.load_source_refs(connection, row["id"]),
                )
                for row in rows
            ]

    def list_entities(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentEntity]:
        if as_of_checkpoint_id is not None:
            items = self._list_persistent_as_of(
                as_of_checkpoint_id,
                "entity",
                user_id=user_id,
                session_id=session_id,
                limit=limit,
            )
            return [item for item in items if isinstance(item, PersistentEntity)]
        conditions, params = _object_scope_conditions(user_id, session_id)
        conditions.insert(0, "o.status = 'active'")
        query = (
            f"{_ENTITY_SELECT} WHERE {' AND '.join(conditions)} "
            "GROUP BY ent.id, o.id, cp.sequence "
            "ORDER BY o.updated_at DESC, ent.id ASC"
        )
        query, params = _with_limit(query, params, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                entity_from_row(
                    row,
                    self.sources.load_source_refs(connection, row["id"]),
                )
                for row in rows
            ]

    def list_descriptions(
        self,
        event_ids: Sequence[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentDescription]:
        if as_of_checkpoint_id is not None:
            items = self._list_persistent_as_of(
                as_of_checkpoint_id,
                "description",
                user_id=user_id,
                session_id=session_id,
                limit=None,
            )
            descriptions = [
                item for item in items if isinstance(item, PersistentDescription)
            ]
            ids = set(_compact_ids(event_ids)) if event_ids is not None else None
            if ids is not None:
                descriptions = [
                    item for item in descriptions if item.event_id in ids
                ]
            return descriptions[: max(0, limit)] if limit is not None else descriptions
        conditions = ["o.status = 'active'"]
        params: list[object] = []
        ids = _compact_ids(event_ids) if event_ids is not None else None
        if ids is not None:
            if not ids:
                return []
            conditions.append(f"d.event_id IN ({_placeholders(ids)})")
            params.extend(ids)
        else:
            scope_conditions, scope_params = _object_scope_conditions(
                user_id,
                session_id,
            )
            conditions.extend(scope_conditions)
            params.extend(scope_params)
        query = (
            f"{_DESCRIPTION_SELECT} WHERE {' AND '.join(conditions)} "
            "ORDER BY o.updated_at DESC, d.id ASC"
        )
        query, params = _with_limit(query, params, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                description_from_row(
                    row,
                    self.sources.load_source_refs(connection, row["id"]),
                )
                for row in rows
            ]

    def list_properties(
        self,
        entity_ids: Sequence[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentProperty]:
        if as_of_checkpoint_id is not None:
            items = self._list_persistent_as_of(
                as_of_checkpoint_id,
                "property",
                user_id=user_id,
                session_id=session_id,
                limit=None,
            )
            properties = [
                item for item in items if isinstance(item, PersistentProperty)
            ]
            ids = set(_compact_ids(entity_ids)) if entity_ids is not None else None
            if ids is not None:
                properties = [item for item in properties if item.entity_id in ids]
            return properties[: max(0, limit)] if limit is not None else properties
        conditions = ["o.status = 'active'"]
        params: list[object] = []
        ids = _compact_ids(entity_ids) if entity_ids is not None else None
        if ids is not None:
            if not ids:
                return []
            conditions.append(f"p.entity_id IN ({_placeholders(ids)})")
            params.extend(ids)
        else:
            scope_conditions, scope_params = _object_scope_conditions(
                user_id,
                session_id,
            )
            conditions.extend(scope_conditions)
            params.extend(scope_params)
        query = (
            f"{_PROPERTY_SELECT} WHERE {' AND '.join(conditions)} "
            "ORDER BY o.updated_at DESC, p.id ASC"
        )
        query, params = _with_limit(query, params, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                property_from_row(
                    row,
                    self.sources.load_source_refs(connection, row["id"]),
                )
                for row in rows
            ]

    def list_links(
        self,
        object_refs: Sequence[PersistentObjectRef] | None = None,
        user_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentLink]:
        if as_of_checkpoint_id is not None:
            items = self._list_persistent_as_of(
                as_of_checkpoint_id,
                "link",
                user_id=user_id,
                session_id=None,
                limit=None,
            )
            links = [item for item in items if isinstance(item, PersistentLink)]
            ref_ids = (
                set(_compact_ids(ref.object_id for ref in object_refs))
                if object_refs is not None
                else None
            )
            if ref_ids is not None:
                links = [
                    item
                    for item in links
                    if item.from_ref.object_id in ref_ids
                    or item.to_ref.object_id in ref_ids
                ]
            links = [
                item
                for item in links
                if self._link_endpoints_visible(item, as_of_checkpoint_id)
            ]
            return links[: max(0, limit)] if limit is not None else links
        conditions = ["o.status = 'active'"]
        params: list[object] = []
        refs = list(object_refs) if object_refs is not None else None
        if refs is not None:
            if not refs:
                return []
            ref_ids = _compact_ids(ref.object_id for ref in refs)
            if not ref_ids:
                return []
            conditions.append(
                f"(r.from_object_id IN ({_placeholders(ref_ids)}) "
                f"OR r.to_object_id IN ({_placeholders(ref_ids)}))"
            )
            params.extend([*ref_ids, *ref_ids])
        if user_id is not None:
            conditions.append("(o.user_id IS NULL OR o.user_id = %s)")
            params.append(user_id)
        query = (
            f"{_RELATION_SELECT} WHERE {' AND '.join(conditions)} "
            "ORDER BY o.updated_at DESC, r.id ASC"
        )
        query, params = _with_limit(query, params, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                link_from_row(
                    row,
                    self.sources.load_source_refs(connection, row["id"]),
                )
                for row in rows
            ]

    def list_time_links(
        self,
        target_refs: Sequence[PersistentObjectRef] | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentTimeLink]:
        if as_of_checkpoint_id is not None:
            items = self._list_persistent_as_of(
                as_of_checkpoint_id,
                "time_link",
                user_id=None,
                session_id=None,
                limit=None,
            )
            time_links = [
                item for item in items if isinstance(item, PersistentTimeLink)
            ]
            target_ids = (
                set(_compact_ids(ref.object_id for ref in target_refs))
                if target_refs is not None
                else None
            )
            if target_ids is not None:
                time_links = [
                    item for item in time_links if item.target_ref.object_id in target_ids
                ]
            time_links = [
                item
                for item in time_links
                if self._time_link_endpoints_visible(item, as_of_checkpoint_id)
            ]
            return time_links[: max(0, limit)] if limit is not None else time_links
        conditions = ["o.status = 'active'"]
        params: list[object] = []
        refs = list(target_refs) if target_refs is not None else None
        if refs is not None:
            if not refs:
                return []
            target_ids = _compact_ids(ref.object_id for ref in refs)
            if not target_ids:
                return []
            conditions.append(f"tl.target_object_id IN ({_placeholders(target_ids)})")
            params.extend(target_ids)
        query = (
            f"{_TIME_LINK_SELECT} WHERE {' AND '.join(conditions)} "
            "ORDER BY o.updated_at DESC, tl.id ASC"
        )
        query, params = _with_limit(query, params, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                time_link_from_row(
                    row,
                    self.sources.load_source_refs(connection, row["id"]),
                )
                for row in rows
            ]

    def list_time_refs(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentTimeRef]:
        if as_of_checkpoint_id is not None:
            items = self._list_persistent_as_of(
                as_of_checkpoint_id,
                "time_ref",
                user_id=user_id,
                session_id=session_id,
                limit=limit,
            )
            return [item for item in items if isinstance(item, PersistentTimeRef)]
        conditions, params = _object_scope_conditions(user_id, session_id)
        conditions.insert(0, "o.status = 'active'")
        query = (
            f"{_TIME_REF_SELECT} WHERE {' AND '.join(conditions)} "
            "ORDER BY o.updated_at DESC, tr.id ASC"
        )
        query, params = _with_limit(query, params, limit)
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                time_ref_from_row(
                    row,
                    self.sources.load_source_refs(connection, row["id"]),
                )
                for row in rows
            ]

    def get_time_refs(
        self,
        time_ref_ids: Sequence[str],
        as_of_checkpoint_id: str | None = None,
    ) -> list[PersistentTimeRef]:
        ids = _compact_ids(time_ref_ids)
        if not ids:
            return []
        if as_of_checkpoint_id is not None:
            refs: list[PersistentTimeRef] = []
            for time_ref_id in ids:
                item = self.get_time_ref(time_ref_id, as_of_checkpoint_id)
                if item is not None:
                    refs.append(item)
            return refs
        with self.database.connect() as connection:
            rows = connection.execute(
                f"{_TIME_REF_SELECT} WHERE tr.id IN ({_placeholders(ids)})",
                tuple(ids),
            ).fetchall()
            refs_by_id = {
                row["id"]: time_ref_from_row(
                    row,
                    self.sources.load_source_refs(connection, row["id"]),
                )
                for row in rows
            }
        return [
            refs_by_id[time_ref_id]
            for time_ref_id in ids
            if time_ref_id in refs_by_id
        ]

    def list_records_as_of(
        self,
        checkpoint_id: str,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        if limit is not None and limit <= 0:
            return []
        with self.database.connect() as connection:
            rows = self._latest_revision_rows_as_of(connection, checkpoint_id)
        records: list[MemoryRecord] = []
        for row in rows:
            status = row["status_after"]
            if not include_inactive and status != "active":
                continue
            item = _persistent_from_revision(row)
            if item is None:
                continue
            if not _persistent_visible_for_scope(
                item,
                row,
                user_id=user_id,
                session_id=session_id,
            ):
                continue
            if status == "active":
                if isinstance(item, PersistentLink) and not self._link_endpoints_visible(
                    item,
                    checkpoint_id,
                ):
                    continue
                if isinstance(
                    item,
                    PersistentTimeLink,
                ) and not self._time_link_endpoints_visible(item, checkpoint_id):
                    continue
            record = _persistent_to_record(item)
            if record is None:
                continue
            records.append(_record_with_revision_metadata(record, row))
            if limit is not None and len(records) >= max(0, limit):
                break
        return records

    def _save_event(
        self,
        connection: Any,
        event: PersistentEvent,
    ) -> PersistentEvent:
        event_id = event.id or new_persistent_id("event")
        self._save_object(
            connection,
            object_id=event_id,
            object_type="event",
            user_id=event.user_id,
            session_id=event.session_id,
            scope=_scope(event.user_id, event.session_id),
            status=event.status,
            confidence=event.confidence,
            importance=event.importance,
            created_turn_id=event.created_turn_id,
            created_checkpoint_id=event.created_checkpoint_id,
            metadata=event.metadata,
        )
        connection.execute(
            """
            INSERT INTO memory_events (id, title, summary, event_type)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                event_type = EXCLUDED.event_type
            """,
            (event_id, event.title, event.summary, event.event_type),
        )
        stored = replace(event, id=event_id)
        self.sources.save_source_refs(connection, event_id, event.source_refs)
        self._save_revision_for_persistent(connection, stored)
        return stored

    def _save_description(
        self,
        connection: Any,
        description: PersistentDescription,
    ) -> PersistentDescription:
        event_id = _required_ref(description.event_id, "description.event_id")
        description_id = description.id or new_persistent_id("description")
        self._save_object(
            connection,
            object_id=description_id,
            object_type="description",
            user_id=description.user_id,
            session_id=description.session_id,
            scope=_scope(description.user_id, description.session_id),
            status="active",
            confidence=description.confidence,
            importance=description.importance,
            created_turn_id=description.created_turn_id,
            created_checkpoint_id=description.created_checkpoint_id,
            metadata=description.metadata,
        )
        connection.execute(
            """
            INSERT INTO memory_descriptions (
                id, event_id, content, description_type
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                event_id = EXCLUDED.event_id,
                content = EXCLUDED.content,
                description_type = EXCLUDED.description_type
            """,
            (
                description_id,
                event_id,
                description.content,
                description.description_type,
            ),
        )
        stored = replace(description, id=description_id, event_id=event_id)
        self.sources.save_source_refs(
            connection,
            description_id,
            description.source_refs,
        )
        self._save_revision_for_persistent(connection, stored)
        return stored

    def _save_entity(
        self,
        connection: Any,
        entity: PersistentEntity,
    ) -> PersistentEntity:
        entity_id = entity.id or new_persistent_id("entity")
        self._save_object(
            connection,
            object_id=entity_id,
            object_type="entity",
            user_id=entity.user_id,
            session_id=entity.session_id,
            scope=entity.scope,
            status="active",
            confidence=entity.confidence,
            importance=entity.importance,
            created_turn_id=entity.created_turn_id,
            created_checkpoint_id=entity.created_checkpoint_id,
            metadata=entity.metadata,
        )
        connection.execute(
            """
            INSERT INTO memory_entities (
                id, name, entity_type, identity_summary
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                entity_type = EXCLUDED.entity_type,
                identity_summary = EXCLUDED.identity_summary
            """,
            (
                entity_id,
                entity.name,
                entity.entity_type,
                entity.identity_summary,
            ),
        )
        connection.execute(
            "DELETE FROM memory_entity_aliases WHERE entity_id = %s",
            (entity_id,),
        )
        for position, alias in enumerate(entity.aliases):
            connection.execute(
                """
                INSERT INTO memory_entity_aliases (entity_id, alias, position)
                VALUES (%s, %s, %s)
                ON CONFLICT (entity_id, alias) DO UPDATE SET
                    position = EXCLUDED.position
                """,
                (entity_id, alias, position),
            )
        stored = replace(entity, id=entity_id)
        self.sources.save_source_refs(connection, entity_id, entity.source_refs)
        self._save_revision_for_persistent(connection, stored)
        return stored

    def _save_property(
        self,
        connection: Any,
        memory_property: PersistentProperty,
    ) -> PersistentProperty:
        entity_id = _required_ref(memory_property.entity_id, "property.entity_id")
        property_id = memory_property.id or new_persistent_id("property")
        self._save_object(
            connection,
            object_id=property_id,
            object_type="property",
            user_id=memory_property.user_id,
            session_id=memory_property.session_id,
            scope=_scope(memory_property.user_id, memory_property.session_id),
            status="active",
            confidence=memory_property.confidence,
            importance=memory_property.importance,
            created_turn_id=memory_property.created_turn_id,
            created_checkpoint_id=memory_property.created_checkpoint_id,
            metadata=memory_property.metadata,
        )
        connection.execute(
            """
            INSERT INTO memory_properties (
                id, entity_id, content, property_type
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                entity_id = EXCLUDED.entity_id,
                content = EXCLUDED.content,
                property_type = EXCLUDED.property_type
            """,
            (
                property_id,
                entity_id,
                memory_property.content,
                memory_property.property_type,
            ),
        )
        stored = replace(memory_property, id=property_id, entity_id=entity_id)
        self.sources.save_source_refs(
            connection,
            property_id,
            memory_property.source_refs,
        )
        self._save_revision_for_persistent(connection, stored)
        return stored

    def _save_link(
        self,
        connection: Any,
        link: PersistentLink,
    ) -> PersistentLink:
        existing_id = self._find_relation_id(connection, link)
        link_id = existing_id or link.id or new_persistent_id("link")
        user_id = _metadata_string(link.metadata, "user_id")
        session_id = _metadata_string(link.metadata, "session_id")
        self._save_object(
            connection,
            object_id=link_id,
            object_type="relation",
            user_id=user_id,
            session_id=session_id,
            scope=_scope(user_id, session_id),
            status="active",
            confidence=link.confidence,
            importance="low",
            created_turn_id=link.created_turn_id,
            created_checkpoint_id=link.created_checkpoint_id,
            metadata=link.metadata,
        )
        row = connection.execute(
            """
            INSERT INTO memory_relations (
                id, from_object_id, to_object_id, relation_type, reason
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (from_object_id, to_object_id, relation_type)
            DO UPDATE SET
                reason = EXCLUDED.reason
            RETURNING id
            """,
            (
                link_id,
                link.from_ref.object_id,
                link.to_ref.object_id,
                link.relation_type,
                link.reason,
            ),
        ).fetchone()
        stored_id = row["id"]
        stored = replace(link, id=stored_id)
        self.sources.save_source_refs(connection, stored_id, link.source_refs)
        self._save_revision_for_persistent(connection, stored)
        return stored

    def _save_time_ref(
        self,
        connection: Any,
        time_ref: PersistentTimeRef,
    ) -> PersistentTimeRef:
        time_ref_id = time_ref.id or new_persistent_id("time_ref")
        user_id = _metadata_string(time_ref.metadata, "user_id")
        session_id = _metadata_string(time_ref.metadata, "session_id")
        self._save_object(
            connection,
            object_id=time_ref_id,
            object_type="time_ref",
            user_id=user_id,
            session_id=session_id,
            scope=_scope(user_id, session_id),
            status="active",
            confidence="medium",
            importance="low",
            created_turn_id=time_ref.created_turn_id,
            created_checkpoint_id=time_ref.created_checkpoint_id,
            metadata=time_ref.metadata,
        )
        connection.execute(
            """
            INSERT INTO memory_time_refs (
                id, raw_text, time_kind, timeline_kind, certainty,
                anchor_timezone, anchor_utc_offset, anchor_message_id,
                resolved_start, resolved_end, granularity, description,
                duration_text, recurrence_text
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                raw_text = EXCLUDED.raw_text,
                time_kind = EXCLUDED.time_kind,
                timeline_kind = EXCLUDED.timeline_kind,
                certainty = EXCLUDED.certainty,
                anchor_timezone = EXCLUDED.anchor_timezone,
                anchor_utc_offset = EXCLUDED.anchor_utc_offset,
                anchor_message_id = EXCLUDED.anchor_message_id,
                resolved_start = EXCLUDED.resolved_start,
                resolved_end = EXCLUDED.resolved_end,
                granularity = EXCLUDED.granularity,
                description = EXCLUDED.description,
                duration_text = EXCLUDED.duration_text,
                recurrence_text = EXCLUDED.recurrence_text
            """,
            (
                time_ref_id,
                time_ref.raw_text,
                time_ref.time_kind,
                time_ref.timeline_kind,
                time_ref.certainty,
                time_ref.anchor_timezone,
                time_ref.anchor_utc_offset,
                time_ref.anchor_message_id,
                time_ref.resolved_start,
                time_ref.resolved_end,
                time_ref.granularity,
                time_ref.description,
                time_ref.duration_text,
                time_ref.recurrence_text,
            ),
        )
        stored = replace(time_ref, id=time_ref_id)
        self.sources.save_source_refs(connection, time_ref_id, time_ref.source_refs)
        self._save_revision_for_persistent(connection, stored)
        return stored

    def _save_time_link(
        self,
        connection: Any,
        time_link: PersistentTimeLink,
    ) -> PersistentTimeLink:
        existing_id = self._find_time_link_id(connection, time_link)
        time_link_id = existing_id or time_link.id or new_persistent_id("time_link")
        user_id = _metadata_string(time_link.metadata, "user_id")
        session_id = _metadata_string(time_link.metadata, "session_id")
        self._save_object(
            connection,
            object_id=time_link_id,
            object_type="time_link",
            user_id=user_id,
            session_id=session_id,
            scope=_scope(user_id, session_id),
            status="active",
            confidence=time_link.confidence,
            importance="low",
            created_turn_id=time_link.created_turn_id,
            created_checkpoint_id=time_link.created_checkpoint_id,
            metadata=time_link.metadata,
        )
        row = connection.execute(
            """
            INSERT INTO memory_time_links (
                id, target_object_id, time_ref_object_id, time_role
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (target_object_id, time_ref_object_id, time_role)
            DO UPDATE SET
                time_role = EXCLUDED.time_role
            RETURNING id
            """,
            (
                time_link_id,
                time_link.target_ref.object_id,
                time_link.time_ref_id,
                time_link.time_role,
            ),
        ).fetchone()
        stored_id = row["id"]
        stored = replace(time_link, id=stored_id)
        self.sources.save_source_refs(connection, stored_id, time_link.source_refs)
        self._save_revision_for_persistent(connection, stored)
        return stored

    def _save_revision_for_persistent(
        self,
        connection: Any,
        item: object,
    ) -> None:
        payload = _payload_for_persistent(item)
        if payload is None:
            return
        metadata = dict(getattr(item, "metadata", {}) or {})
        object_id = getattr(item, "id", None)
        if not isinstance(object_id, str) or not object_id:
            return
        self._save_revision(
            connection,
            object_id=object_id,
            checkpoint_id=getattr(item, "created_checkpoint_id", None),
            turn_id=getattr(item, "created_turn_id", None),
            operation=_revision_operation(metadata.get("write_action")),
            status_after=getattr(item, "status", "active"),
            confidence=getattr(item, "confidence", "medium"),
            importance=getattr(item, "importance", "medium"),
            payload=payload,
            source_refs=[
                ref.to_record()
                for ref in getattr(item, "source_refs", [])
                if hasattr(ref, "to_record")
            ],
            metadata=metadata,
            merged_into_object_id=_metadata_string(metadata, "merged_into_object_id"),
        )

    def _save_revision(
        self,
        connection: Any,
        *,
        object_id: str,
        checkpoint_id: str | None,
        turn_id: str | None,
        operation: str,
        status_after: str,
        confidence: str,
        importance: str,
        payload: dict[str, Any],
        source_refs: list[dict[str, Any]],
        metadata: dict[str, Any],
        merged_into_object_id: str | None = None,
    ) -> None:
        previous = connection.execute(
            """
            SELECT revision_id FROM memory_revisions
            WHERE object_id = %s
            ORDER BY created_at DESC, operation_index DESC, revision_id DESC
            LIMIT 1
            """,
            (object_id,),
        ).fetchone()
        index_row = connection.execute(
            """
            SELECT COALESCE(MAX(operation_index), -1) + 1 AS next_index
            FROM memory_revisions
            WHERE checkpoint_id IS NOT DISTINCT FROM %s
            """,
            (checkpoint_id,),
        ).fetchone()
        connection.execute(
            """
            INSERT INTO memory_revisions (
                revision_id, object_id, checkpoint_id, turn_id, operation,
                status_after, confidence, importance, payload, source_refs,
                metadata, previous_revision_id, merged_into_object_id,
                operation_index
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                new_persistent_id("rev"),
                object_id,
                checkpoint_id,
                turn_id,
                operation,
                status_after,
                confidence,
                importance,
                Jsonb(payload),
                Jsonb(source_refs),
                Jsonb(dict(metadata)),
                previous["revision_id"] if previous else None,
                merged_into_object_id,
                index_row["next_index"] if index_row else 0,
            ),
        )

    def _latest_revision_payload(
        self,
        connection: Any,
        object_id: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        row = connection.execute(
            """
            SELECT payload, source_refs FROM memory_revisions
            WHERE object_id = %s
            ORDER BY created_at DESC, operation_index DESC, revision_id DESC
            LIMIT 1
            """,
            (object_id,),
        ).fetchone()
        if not row:
            return {}, []
        payload = row["payload"] if isinstance(row["payload"], dict) else {}
        source_refs = row["source_refs"] if isinstance(row["source_refs"], list) else []
        return dict(payload), [dict(item) for item in source_refs if isinstance(item, dict)]

    def _persistent_as_of(
        self,
        connection: Any,
        object_id: str,
        checkpoint_id: str,
    ) -> object | None:
        rows = self._latest_revision_rows_as_of(
            connection,
            checkpoint_id,
            object_id=object_id,
        )
        if not rows:
            return None
        row = rows[0]
        if row["status_after"] != "active":
            return None
        return _persistent_from_revision(row)

    def _list_persistent_as_of(
        self,
        checkpoint_id: str,
        memory_type: str,
        *,
        user_id: str | None,
        session_id: str | None,
        limit: int | None,
    ) -> list[object]:
        if limit is not None and limit <= 0:
            return []
        with self.database.connect() as connection:
            rows = self._latest_revision_rows_as_of(connection, checkpoint_id)
        result: list[object] = []
        for row in rows:
            if row["status_after"] != "active":
                continue
            item = _persistent_from_revision(row)
            if item is None or _memory_type_for_persistent(item) != memory_type:
                continue
            if not _persistent_visible_for_scope(
                item,
                row,
                user_id=user_id,
                session_id=session_id,
            ):
                continue
            result.append(item)
            if limit is not None and len(result) >= max(0, limit):
                break
        return result

    def _latest_revision_rows_as_of(
        self,
        connection: Any,
        checkpoint_id: str,
        *,
        object_id: str | None = None,
    ) -> list[dict[str, Any]]:
        object_filter = "AND mr.object_id = %s" if object_id is not None else ""
        params: list[object] = [checkpoint_id]
        if object_id is not None:
            params.append(object_id)
        rows = connection.execute(
            f"""
            WITH visible AS (
                SELECT
                    mr.*,
                    o.object_type,
                    o.user_id,
                    o.session_id,
                    o.scope,
                    o.created_turn_id AS object_created_turn_id,
                    o.created_checkpoint_id AS object_created_checkpoint_id,
                    ca.depth,
                    ROW_NUMBER() OVER (
                        PARTITION BY mr.object_id
                        ORDER BY
                            CASE
                                WHEN mr.checkpoint_id IS NULL THEN 2147483647
                                ELSE ca.depth
                            END ASC,
                            mr.operation_index DESC,
                            mr.created_at DESC,
                            mr.revision_id DESC
                    ) AS rn
                FROM memory_revisions mr
                JOIN memory_objects o ON o.id = mr.object_id
                LEFT JOIN checkpoint_ancestry ca
                  ON ca.ancestor_checkpoint_id = mr.checkpoint_id
                 AND ca.descendant_checkpoint_id = %s
                WHERE (mr.checkpoint_id IS NULL OR ca.ancestor_checkpoint_id IS NOT NULL)
                {object_filter}
            )
            SELECT * FROM visible
            WHERE rn = 1
            ORDER BY created_at DESC, operation_index DESC, object_id ASC
            """,
            tuple(params),
        ).fetchall()
        return [dict(row) for row in rows]

    def _link_endpoints_visible(
        self,
        link: PersistentLink,
        checkpoint_id: str,
    ) -> bool:
        return (
            self.get_record_as_of(link.from_ref.object_id, checkpoint_id) is not None
            and self.get_record_as_of(link.to_ref.object_id, checkpoint_id) is not None
        )

    def _time_link_endpoints_visible(
        self,
        time_link: PersistentTimeLink,
        checkpoint_id: str,
    ) -> bool:
        return (
            self.get_record_as_of(time_link.target_ref.object_id, checkpoint_id)
            is not None
            and self.get_record_as_of(time_link.time_ref_id, checkpoint_id) is not None
        )

    def _get_current_any(self, record_id: str) -> object | None:
        for loader in (
            self.get_event,
            self.get_description,
            self.get_entity,
            self.get_property,
            self.get_link,
            self.get_time_ref,
            self.get_time_link,
        ):
            item = loader(record_id)
            if item is not None:
                return item
        return None

    def _save_object(
        self,
        connection: Any,
        *,
        object_id: str,
        object_type: str,
        user_id: str | None,
        session_id: str | None,
        scope: str,
        status: str,
        confidence: str,
        importance: str,
        created_turn_id: str | None,
        created_checkpoint_id: str | None,
        metadata: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO memory_objects (
                id, object_type, user_id, session_id, scope, status,
                confidence, importance, created_turn_id, created_checkpoint_id,
                metadata
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                object_type = EXCLUDED.object_type,
                user_id = EXCLUDED.user_id,
                session_id = EXCLUDED.session_id,
                scope = EXCLUDED.scope,
                status = EXCLUDED.status,
                confidence = EXCLUDED.confidence,
                importance = EXCLUDED.importance,
                created_turn_id = COALESCE(memory_objects.created_turn_id, EXCLUDED.created_turn_id),
                created_checkpoint_id = COALESCE(memory_objects.created_checkpoint_id, EXCLUDED.created_checkpoint_id),
                metadata = EXCLUDED.metadata,
                updated_at = NOW()
            """,
            (
                object_id,
                object_type,
                user_id,
                session_id,
                scope,
                status,
                confidence,
                importance,
                created_turn_id,
                created_checkpoint_id,
                Jsonb(dict(metadata)),
            ),
        )

    def _find_relation_id(
        self,
        connection: Any,
        link: PersistentLink,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT id FROM memory_relations
            WHERE from_object_id = %s
              AND to_object_id = %s
              AND relation_type = %s
            """,
            (
                link.from_ref.object_id,
                link.to_ref.object_id,
                link.relation_type,
            ),
        ).fetchone()
        return row["id"] if row else None

    def _find_time_link_id(
        self,
        connection: Any,
        time_link: PersistentTimeLink,
    ) -> str | None:
        row = connection.execute(
            """
            SELECT id FROM memory_time_links
            WHERE target_object_id = %s
              AND time_ref_object_id = %s
              AND time_role = %s
            """,
            (
                time_link.target_ref.object_id,
                time_link.time_ref_id,
                time_link.time_role,
            ),
        ).fetchone()
        return row["id"] if row else None


_OBJECT_COLUMNS = """
    o.user_id,
    o.session_id,
    o.scope,
    o.status,
    o.confidence,
    o.importance,
    o.created_turn_id,
    o.created_checkpoint_id,
    cp.sequence AS created_checkpoint_sequence,
    o.created_at,
    o.updated_at,
    o.merged_into_object_id,
    o.deleted_at,
    o.deleted_reason,
    o.metadata
"""

_OBJECT_JOIN = """
    JOIN memory_objects o ON o.id = {id_expression}
    LEFT JOIN conversation_checkpoints cp ON cp.id = o.created_checkpoint_id
"""

_EVENT_SELECT = f"""
    SELECT
        e.id, e.title, e.summary, e.event_type,
        {_OBJECT_COLUMNS}
    FROM memory_events e
    {_OBJECT_JOIN.format(id_expression='e.id')}
"""

_DESCRIPTION_SELECT = f"""
    SELECT
        d.id, d.event_id, d.content, d.description_type,
        {_OBJECT_COLUMNS}
    FROM memory_descriptions d
    {_OBJECT_JOIN.format(id_expression='d.id')}
"""

_ENTITY_SELECT = f"""
    SELECT
        ent.id, ent.name, ent.entity_type, ent.identity_summary,
        COALESCE(
            jsonb_agg(a.alias ORDER BY a.position)
                FILTER (WHERE a.alias IS NOT NULL),
            '[]'::jsonb
        ) AS aliases,
        {_OBJECT_COLUMNS}
    FROM memory_entities ent
    {_OBJECT_JOIN.format(id_expression='ent.id')}
    LEFT JOIN memory_entity_aliases a ON a.entity_id = ent.id
"""

_PROPERTY_SELECT = f"""
    SELECT
        p.id, p.entity_id, p.content, p.property_type,
        {_OBJECT_COLUMNS}
    FROM memory_properties p
    {_OBJECT_JOIN.format(id_expression='p.id')}
"""

_RELATION_SELECT = f"""
    SELECT
        r.id,
        from_object.object_type AS from_type,
        r.from_object_id AS from_id,
        to_object.object_type AS to_type,
        r.to_object_id AS to_id,
        r.relation_type,
        r.reason,
        {_OBJECT_COLUMNS}
    FROM memory_relations r
    {_OBJECT_JOIN.format(id_expression='r.id')}
    JOIN memory_objects from_object ON from_object.id = r.from_object_id
    JOIN memory_objects to_object ON to_object.id = r.to_object_id
"""

_TIME_REF_SELECT = f"""
    SELECT
        tr.id, tr.raw_text, tr.time_kind, tr.timeline_kind, tr.certainty,
        tr.anchor_timezone, tr.anchor_utc_offset, tr.anchor_message_id,
        tr.resolved_start, tr.resolved_end, tr.granularity, tr.description,
        tr.duration_text, tr.recurrence_text,
        {_OBJECT_COLUMNS}
    FROM memory_time_refs tr
    {_OBJECT_JOIN.format(id_expression='tr.id')}
"""

_TIME_LINK_SELECT = f"""
    SELECT
        tl.id,
        target_object.object_type AS target_type,
        tl.target_object_id AS target_id,
        tl.time_ref_object_id AS time_ref_id,
        tl.time_role,
        {_OBJECT_COLUMNS}
    FROM memory_time_links tl
    {_OBJECT_JOIN.format(id_expression='tl.id')}
    JOIN memory_objects target_object ON target_object.id = tl.target_object_id
"""


def _required_ref(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _metadata_string(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _scope(user_id: str | None, session_id: str | None) -> str:
    if session_id is not None:
        return "session"
    if user_id is not None:
        return "user"
    return "global"


def _object_scope_conditions(
    user_id: str | None,
    session_id: str | None,
) -> tuple[list[str], list[object]]:
    conditions: list[str] = []
    params: list[object] = []
    if user_id is not None or session_id is not None:
        conditions.append("(o.user_id IS NULL OR o.user_id = %s)")
        params.append(user_id)
        conditions.append("(o.session_id IS NULL OR o.session_id = %s)")
        params.append(session_id)
    else:
        conditions.append("TRUE")
    return conditions, params


def _compact_ids(values: Sequence[str | None]) -> list[str]:
    return [value for value in values if value]


def _placeholders(values: Sequence[object]) -> str:
    return ", ".join(["%s"] * len(values))


def _with_limit(
    query: str,
    params: list[object],
    limit: int | None,
) -> tuple[str, list[object]]:
    if limit is None:
        return query, params
    return f"{query} LIMIT %s", [*params, max(0, limit)]


def _revision_operation(value: object) -> str:
    if value in {
        "create",
        "reuse",
        "attach",
        "update",
        "merge",
        "invalidate",
        "flag_conflict",
        "ignore",
        "seed",
    }:
        return str(value)
    return "seed"


def _payload_for_persistent(item: object) -> dict[str, Any] | None:
    if isinstance(item, PersistentEvent):
        return {
            "memory_type": "event",
            "id": item.id,
            "title": item.title,
            "summary": item.summary,
            "event_type": item.event_type,
        }
    if isinstance(item, PersistentDescription):
        return {
            "memory_type": "description",
            "id": item.id,
            "event_id": item.event_id,
            "content": item.content,
            "description_type": item.description_type,
        }
    if isinstance(item, PersistentEntity):
        return {
            "memory_type": "entity",
            "id": item.id,
            "name": item.name,
            "entity_type": item.entity_type,
            "identity_summary": item.identity_summary,
            "aliases": list(item.aliases),
        }
    if isinstance(item, PersistentProperty):
        return {
            "memory_type": "property",
            "id": item.id,
            "entity_id": item.entity_id,
            "content": item.content,
            "property_type": item.property_type,
        }
    if isinstance(item, PersistentLink):
        return {
            "memory_type": "link",
            "id": item.id,
            "from_type": item.from_ref.object_type,
            "from_id": item.from_ref.object_id,
            "to_type": item.to_ref.object_type,
            "to_id": item.to_ref.object_id,
            "relation_type": item.relation_type,
            "reason": item.reason,
        }
    if isinstance(item, PersistentTimeRef):
        return {
            "memory_type": "time_ref",
            "id": item.id,
            "raw_text": item.raw_text,
            "time_kind": item.time_kind,
            "timeline_kind": item.timeline_kind,
            "certainty": item.certainty,
            "anchor_timezone": item.anchor_timezone,
            "anchor_utc_offset": item.anchor_utc_offset,
            "anchor_message_id": item.anchor_message_id,
            "resolved_start": item.resolved_start,
            "resolved_end": item.resolved_end,
            "granularity": item.granularity,
            "description": item.description,
            "duration_text": item.duration_text,
            "recurrence_text": item.recurrence_text,
        }
    if isinstance(item, PersistentTimeLink):
        return {
            "memory_type": "time_link",
            "id": item.id,
            "target_type": item.target_ref.object_type,
            "target_id": item.target_ref.object_id,
            "time_ref_id": item.time_ref_id,
            "time_role": item.time_role,
        }
    return None


def _persistent_from_revision(row: dict[str, Any]) -> object | None:
    payload = row.get("payload")
    if not isinstance(payload, dict):
        return None
    metadata = dict(row.get("metadata") or {})
    source_refs = _source_refs_from_revision(row.get("source_refs"))
    memory_type = payload.get("memory_type")
    common = {
        "user_id": row.get("user_id"),
        "session_id": row.get("session_id"),
        "source_refs": source_refs,
        "confidence": row.get("confidence") or "medium",
        "created_turn_id": row.get("turn_id") or row.get("object_created_turn_id"),
        "created_checkpoint_id": (
            row.get("checkpoint_id") or row.get("object_created_checkpoint_id")
        ),
        "metadata": metadata,
    }
    if memory_type == "event":
        return PersistentEvent(
            id=payload.get("id") or row.get("object_id"),
            title=str(payload.get("title") or ""),
            summary=_optional_payload_string(payload, "summary"),
            event_type=_optional_payload_string(payload, "event_type"),
            status=row.get("status_after") or "active",
            importance=row.get("importance") or "medium",
            **common,
        )
    if memory_type == "description":
        return PersistentDescription(
            id=payload.get("id") or row.get("object_id"),
            event_id=_optional_payload_string(payload, "event_id"),
            content=str(payload.get("content") or ""),
            description_type=_optional_payload_string(payload, "description_type"),
            importance=row.get("importance") or "low",
            **common,
        )
    if memory_type == "entity":
        return PersistentEntity(
            id=payload.get("id") or row.get("object_id"),
            name=str(payload.get("name") or ""),
            entity_type=str(payload.get("entity_type") or "unknown"),
            identity_summary=_optional_payload_string(payload, "identity_summary"),
            aliases=_payload_string_list(payload.get("aliases")),
            scope=row.get("scope") or metadata.get("scope") or "session",
            importance=row.get("importance") or "medium",
            **common,
        )
    if memory_type == "property":
        return PersistentProperty(
            id=payload.get("id") or row.get("object_id"),
            entity_id=_optional_payload_string(payload, "entity_id"),
            content=str(payload.get("content") or ""),
            property_type=_optional_payload_string(payload, "property_type"),
            importance=row.get("importance") or "medium",
            **common,
        )
    if memory_type == "link":
        return PersistentLink(
            id=payload.get("id") or row.get("object_id"),
            from_ref=PersistentObjectRef(
                object_type=payload.get("from_type") or "entity",
                object_id=str(payload.get("from_id") or ""),
            ),
            to_ref=PersistentObjectRef(
                object_type=payload.get("to_type") or "entity",
                object_id=str(payload.get("to_id") or ""),
            ),
            relation_type=str(payload.get("relation_type") or "related_to"),
            reason=_optional_payload_string(payload, "reason"),
            source_refs=source_refs,
            confidence=row.get("confidence") or "medium",
            created_turn_id=row.get("turn_id") or row.get("object_created_turn_id"),
            created_checkpoint_id=(
                row.get("checkpoint_id") or row.get("object_created_checkpoint_id")
            ),
            metadata=metadata,
        )
    if memory_type == "time_ref":
        return PersistentTimeRef(
            id=payload.get("id") or row.get("object_id"),
            raw_text=str(payload.get("raw_text") or ""),
            time_kind=payload.get("time_kind") or "vague",
            timeline_kind=payload.get("timeline_kind") or "real_world",
            certainty=payload.get("certainty") or "unknown",
            anchor_timezone=str(payload.get("anchor_timezone") or "UTC"),
            anchor_utc_offset=str(payload.get("anchor_utc_offset") or "+00:00"),
            anchor_message_id=_optional_payload_string(payload, "anchor_message_id"),
            resolved_start=_optional_payload_string(payload, "resolved_start"),
            resolved_end=_optional_payload_string(payload, "resolved_end"),
            granularity=_optional_payload_string(payload, "granularity"),
            description=_optional_payload_string(payload, "description"),
            duration_text=_optional_payload_string(payload, "duration_text"),
            recurrence_text=_optional_payload_string(payload, "recurrence_text"),
            source_refs=source_refs,
            created_turn_id=row.get("turn_id") or row.get("object_created_turn_id"),
            created_checkpoint_id=(
                row.get("checkpoint_id") or row.get("object_created_checkpoint_id")
            ),
            metadata=metadata,
        )
    if memory_type == "time_link":
        return PersistentTimeLink(
            id=payload.get("id") or row.get("object_id"),
            target_ref=PersistentObjectRef(
                object_type=payload.get("target_type") or "event",
                object_id=str(payload.get("target_id") or ""),
            ),
            time_ref_id=str(payload.get("time_ref_id") or ""),
            time_role=str(payload.get("time_role") or "mentioned_at"),
            source_refs=source_refs,
            confidence=row.get("confidence") or "medium",
            created_turn_id=row.get("turn_id") or row.get("object_created_turn_id"),
            created_checkpoint_id=(
                row.get("checkpoint_id") or row.get("object_created_checkpoint_id")
            ),
            metadata=metadata,
        )
    return None


def _persistent_to_record(item: object | None) -> MemoryRecord | None:
    if isinstance(item, PersistentEvent):
        return MemoryRecord(
            id=item.id,
            memory_type="event",
            text=item.title,
            source_refs=_memory_source_refs(item.source_refs),
            metadata={
                **dict(item.metadata),
                "summary": item.summary,
                "event_type": item.event_type,
                "status": item.status,
                "user_id": item.user_id,
                "session_id": item.session_id,
                "confidence": item.confidence,
                "importance": item.importance,
            },
        )
    if isinstance(item, PersistentDescription):
        return MemoryRecord(
            id=item.id,
            memory_type="description",
            text=item.content,
            source_refs=_memory_source_refs(item.source_refs),
            metadata={
                **dict(item.metadata),
                "attached_to_record_id": item.event_id,
                "description_type": item.description_type,
                "user_id": item.user_id,
                "session_id": item.session_id,
                "confidence": item.confidence,
                "importance": item.importance,
            },
        )
    if isinstance(item, PersistentEntity):
        return MemoryRecord(
            id=item.id,
            memory_type="entity",
            text=item.name,
            source_refs=_memory_source_refs(item.source_refs),
            metadata={
                **dict(item.metadata),
                "entity_type": item.entity_type,
                "identity_summary": item.identity_summary,
                "aliases": list(item.aliases),
                "user_id": item.user_id,
                "session_id": item.session_id,
                "scope": item.scope,
                "confidence": item.confidence,
                "importance": item.importance,
            },
        )
    if isinstance(item, PersistentProperty):
        return MemoryRecord(
            id=item.id,
            memory_type="property",
            text=item.content,
            source_refs=_memory_source_refs(item.source_refs),
            metadata={
                **dict(item.metadata),
                "attached_to_record_id": item.entity_id,
                "property_type": item.property_type,
                "user_id": item.user_id,
                "session_id": item.session_id,
                "confidence": item.confidence,
                "importance": item.importance,
            },
        )
    if isinstance(item, PersistentLink):
        return MemoryRecord(
            id=item.id,
            memory_type="link",
            text=f"{item.from_ref.object_type} {item.relation_type} {item.to_ref.object_type}",
            source_refs=_memory_source_refs(item.source_refs),
            metadata={
                **dict(item.metadata),
                "from_type": item.from_ref.object_type,
                "from_record_id": item.from_ref.object_id,
                "to_type": item.to_ref.object_type,
                "to_record_id": item.to_ref.object_id,
                "relation_type": item.relation_type,
                "confidence": item.confidence,
            },
        )
    if isinstance(item, PersistentTimeRef):
        return MemoryRecord(
            id=item.id,
            memory_type="time_ref",
            text=item.raw_text,
            source_refs=_memory_source_refs(item.source_refs),
            metadata={
                **dict(item.metadata),
                "raw_text": item.raw_text,
                "time_kind": item.time_kind,
                "timeline_kind": item.timeline_kind,
                "certainty": item.certainty,
                "anchor_timezone": item.anchor_timezone,
                "anchor_utc_offset": item.anchor_utc_offset,
                "anchor_message_id": item.anchor_message_id,
                "resolved_start": item.resolved_start,
                "resolved_end": item.resolved_end,
                "granularity": item.granularity,
                "description": item.description,
                "duration_text": item.duration_text,
                "recurrence_text": item.recurrence_text,
            },
        )
    if isinstance(item, PersistentTimeLink):
        return MemoryRecord(
            id=item.id,
            memory_type="time_link",
            text=f"{item.target_ref.object_type} {item.time_role} time_ref",
            source_refs=_memory_source_refs(item.source_refs),
            metadata={
                **dict(item.metadata),
                "target_type": item.target_ref.object_type,
                "target_record_id": item.target_ref.object_id,
                "time_ref_record_id": item.time_ref_id,
                "time_role": item.time_role,
                "confidence": item.confidence,
            },
        )
    return None


def _record_with_revision_metadata(
    record: MemoryRecord,
    row: dict[str, Any],
) -> MemoryRecord:
    revision_metadata = {
        "status": row.get("status_after"),
        "revision_operation": row.get("operation"),
        "revision_id": row.get("revision_id"),
        "revision_checkpoint_id": row.get("checkpoint_id"),
        "revision_turn_id": row.get("turn_id"),
        "merged_into_object_id": row.get("merged_into_object_id"),
        "operation_index": row.get("operation_index"),
    }
    metadata = {
        **dict(record.metadata),
        **{key: value for key, value in revision_metadata.items() if value is not None},
    }
    return replace(record, metadata=metadata)


def _memory_type_for_persistent(item: object) -> str | None:
    if isinstance(item, PersistentEvent):
        return "event"
    if isinstance(item, PersistentDescription):
        return "description"
    if isinstance(item, PersistentEntity):
        return "entity"
    if isinstance(item, PersistentProperty):
        return "property"
    if isinstance(item, PersistentLink):
        return "link"
    if isinstance(item, PersistentTimeRef):
        return "time_ref"
    if isinstance(item, PersistentTimeLink):
        return "time_link"
    return None


def _persistent_visible_for_scope(
    item: object,
    row: dict[str, Any],
    *,
    user_id: str | None,
    session_id: str | None,
) -> bool:
    item_user_id = getattr(item, "user_id", None)
    metadata = getattr(item, "metadata", {}) or {}
    if item_user_id is None and isinstance(metadata, dict):
        item_user_id = metadata.get("user_id")
    if user_id is not None and item_user_id not in (None, user_id):
        return False
    item_session_id = getattr(item, "session_id", None)
    if item_session_id is None and isinstance(metadata, dict):
        item_session_id = metadata.get("session_id")
    if (
        session_id is not None
        and row.get("checkpoint_id") is None
        and item_session_id not in (None, session_id)
    ):
        return False
    return True


def _source_refs_from_revision(value: object) -> list[PersistentSourceRef]:
    if not isinstance(value, list):
        return []
    refs: list[PersistentSourceRef] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source_type = item.get("source_type")
        source_id = item.get("source_id")
        if not isinstance(source_type, str) or not isinstance(source_id, str):
            continue
        refs.append(
            PersistentSourceRef(
                source_type=source_type,
                source_id=source_id,
                quote=_optional_payload_string(item, "quote"),
                span_start=item.get("span_start")
                if isinstance(item.get("span_start"), int)
                else None,
                span_end=item.get("span_end")
                if isinstance(item.get("span_end"), int)
                else None,
                metadata=dict(item.get("metadata") or {}),
            )
        )
    return refs


def _memory_source_refs(
    refs: list[PersistentSourceRef],
) -> list[MemorySourceRef]:
    return [
        MemorySourceRef(
            source_type=ref.source_type,
            source_id=ref.source_id,
            quote=ref.quote,
            span_start=ref.span_start,
            span_end=ref.span_end,
            metadata=dict(ref.metadata),
        )
        for ref in refs
    ]


def _optional_payload_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) else None


def _payload_string_list(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
