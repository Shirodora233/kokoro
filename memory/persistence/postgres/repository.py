"""PostgreSQL repository for normalized durable memory objects."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from psycopg.types.json import Jsonb

from ..interfaces import PersistentMemoryRepository
from ..models import (
    PersistentDescription,
    PersistentEntity,
    PersistentEvent,
    PersistentLink,
    PersistentMemoryBundle,
    PersistentObjectRef,
    PersistentProperty,
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
    """Repository for the normalized memory tables.

    This layer is intentionally separate from `PostgresMemoryStore`, which
    persists the current generic `MemoryRecord` envelope.
    """

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
        entities = [
            self._save_entity(connection, entity)
            for entity in bundle.entities
        ]
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

    def get_event(self, event_id: str) -> PersistentEvent | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_events WHERE id = %s",
                (event_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, "event", event_id)
        return event_from_row(row, source_refs)

    def get_description(self, description_id: str) -> PersistentDescription | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_descriptions WHERE id = %s",
                (description_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(
                connection,
                "description",
                description_id,
            )
        return description_from_row(row, source_refs)

    def get_entity(self, entity_id: str) -> PersistentEntity | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_entities WHERE id = %s",
                (entity_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, "entity", entity_id)
        return entity_from_row(row, source_refs)

    def get_property(self, property_id: str) -> PersistentProperty | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_properties WHERE id = %s",
                (property_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(
                connection,
                "property",
                property_id,
            )
        return property_from_row(row, source_refs)

    def get_link(self, link_id: str) -> PersistentLink | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_links WHERE id = %s",
                (link_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, "link", link_id)
        return link_from_row(row, source_refs)

    def get_time_ref(self, time_ref_id: str) -> PersistentTimeRef | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_time_refs WHERE id = %s",
                (time_ref_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(
                connection,
                "time_ref",
                time_ref_id,
            )
        return time_ref_from_row(row, source_refs)

    def get_time_link(self, time_link_id: str) -> PersistentTimeLink | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM memory_time_links WHERE id = %s",
                (time_link_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(
                connection,
                "time_link",
                time_link_id,
            )
        return time_link_from_row(row, source_refs)

    def list_events(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentEvent]:
        conditions = ["status = 'active'"]
        params: list[object] = []
        if user_id is not None or session_id is not None:
            conditions.append("(user_id IS NULL OR user_id = %s)")
            params.append(user_id)
            conditions.append("(session_id IS NULL OR session_id = %s)")
            params.append(session_id)
        query = (
            "SELECT * FROM memory_events WHERE "
            + " AND ".join(conditions)
            + " ORDER BY updated_at DESC, id ASC"
        )
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, limit))
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                event_from_row(
                    row,
                    self.sources.load_source_refs(connection, "event", row["id"]),
                )
                for row in rows
            ]

    def list_entities(
        self,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentEntity]:
        conditions: list[str] = []
        params: list[object] = []
        if user_id is not None or session_id is not None:
            conditions.append("(user_id IS NULL OR user_id = %s)")
            params.append(user_id)
            conditions.append("(session_id IS NULL OR session_id = %s)")
            params.append(session_id)
        query = "SELECT * FROM memory_entities"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY updated_at DESC, id ASC"
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, limit))
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                entity_from_row(
                    row,
                    self.sources.load_source_refs(connection, "entity", row["id"]),
                )
                for row in rows
            ]

    def list_descriptions(
        self,
        event_ids: Sequence[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentDescription]:
        conditions = ["status = 'active'"]
        params: list[object] = []
        ids = _compact_ids(event_ids) if event_ids is not None else None
        if ids is not None:
            if not ids:
                return []
            conditions.append(f"event_id IN ({_placeholders(ids)})")
            params.extend(ids)
        elif user_id is not None or session_id is not None:
            conditions.append("(user_id IS NULL OR user_id = %s)")
            params.append(user_id)
            conditions.append("(session_id IS NULL OR session_id = %s)")
            params.append(session_id)
        query = (
            "SELECT * FROM memory_descriptions WHERE "
            + " AND ".join(conditions)
            + " ORDER BY updated_at DESC, id ASC"
        )
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, limit))
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                description_from_row(
                    row,
                    self.sources.load_source_refs(
                        connection,
                        "description",
                        row["id"],
                    ),
                )
                for row in rows
            ]

    def list_properties(
        self,
        entity_ids: Sequence[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentProperty]:
        conditions = ["status = 'active'"]
        params: list[object] = []
        ids = _compact_ids(entity_ids) if entity_ids is not None else None
        if ids is not None:
            if not ids:
                return []
            conditions.append(f"entity_id IN ({_placeholders(ids)})")
            params.extend(ids)
        elif user_id is not None or session_id is not None:
            conditions.append("(user_id IS NULL OR user_id = %s)")
            params.append(user_id)
            conditions.append("(session_id IS NULL OR session_id = %s)")
            params.append(session_id)
        query = (
            "SELECT * FROM memory_properties WHERE "
            + " AND ".join(conditions)
            + " ORDER BY updated_at DESC, id ASC"
        )
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, limit))
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                property_from_row(
                    row,
                    self.sources.load_source_refs(connection, "property", row["id"]),
                )
                for row in rows
            ]

    def list_links(
        self,
        object_refs: Sequence[PersistentObjectRef] | None = None,
        user_id: str | None = None,
        limit: int | None = None,
    ) -> list[PersistentLink]:
        conditions = ["status = 'active'"]
        params: list[object] = []
        refs = list(object_refs) if object_refs is not None else None
        if refs is not None:
            if not refs:
                return []
            ref_conditions: list[str] = []
            for ref in refs:
                ref_conditions.append(
                    "((from_type = %s AND from_id = %s) "
                    "OR (to_type = %s AND to_id = %s))"
                )
                params.extend(
                    [
                        ref.object_type,
                        ref.object_id,
                        ref.object_type,
                        ref.object_id,
                    ]
                )
            conditions.append("(" + " OR ".join(ref_conditions) + ")")
        if user_id is not None:
            conditions.append("(user_id IS NULL OR user_id = %s)")
            params.append(user_id)
        query = (
            "SELECT * FROM memory_links WHERE "
            + " AND ".join(conditions)
            + " ORDER BY updated_at DESC, id ASC"
        )
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, limit))
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                link_from_row(
                    row,
                    self.sources.load_source_refs(connection, "link", row["id"]),
                )
                for row in rows
            ]

    def list_time_links(
        self,
        target_refs: Sequence[PersistentObjectRef] | None = None,
        limit: int | None = None,
    ) -> list[PersistentTimeLink]:
        conditions: list[str] = []
        params: list[object] = []
        refs = list(target_refs) if target_refs is not None else None
        if refs is not None:
            if not refs:
                return []
            ref_conditions: list[str] = []
            for ref in refs:
                ref_conditions.append("(target_type = %s AND target_id = %s)")
                params.extend([ref.object_type, ref.object_id])
            conditions.append("(" + " OR ".join(ref_conditions) + ")")
        query = "SELECT * FROM memory_time_links"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY updated_at DESC, id ASC"
        if limit is not None:
            query += " LIMIT %s"
            params.append(max(0, limit))
        with self.database.connect() as connection:
            rows = connection.execute(query, tuple(params)).fetchall()
            return [
                time_link_from_row(
                    row,
                    self.sources.load_source_refs(connection, "time_link", row["id"]),
                )
                for row in rows
            ]

    def get_time_refs(
        self,
        time_ref_ids: Sequence[str],
    ) -> list[PersistentTimeRef]:
        ids = _compact_ids(time_ref_ids)
        if not ids:
            return []
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM memory_time_refs
                WHERE id IN ({_placeholders(ids)})
                """,
                tuple(ids),
            ).fetchall()
            refs_by_id = {
                row["id"]: time_ref_from_row(
                    row,
                    self.sources.load_source_refs(
                        connection,
                        "time_ref",
                        row["id"],
                    ),
                )
                for row in rows
            }
        return [
            refs_by_id[time_ref_id]
            for time_ref_id in ids
            if time_ref_id in refs_by_id
        ]

    def _save_event(
        self,
        connection: Any,
        event: PersistentEvent,
    ) -> PersistentEvent:
        event_id = event.id or new_persistent_id("event")
        connection.execute(
            """
            INSERT INTO memory_events (
                id, user_id, session_id, title, summary, event_type, status,
                confidence, importance, metadata, created_turn_id,
                created_checkpoint_id, created_checkpoint_sequence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                session_id = EXCLUDED.session_id,
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                event_type = EXCLUDED.event_type,
                status = EXCLUDED.status,
                confidence = EXCLUDED.confidence,
                importance = EXCLUDED.importance,
                metadata = EXCLUDED.metadata,
                created_turn_id = EXCLUDED.created_turn_id,
                created_checkpoint_id = EXCLUDED.created_checkpoint_id,
                created_checkpoint_sequence = EXCLUDED.created_checkpoint_sequence,
                updated_at = NOW()
            """,
            (
                event_id,
                event.user_id,
                event.session_id,
                event.title,
                event.summary,
                event.event_type,
                event.status,
                event.confidence,
                event.importance,
                Jsonb(dict(event.metadata)),
                event.created_turn_id,
                event.created_checkpoint_id,
                event.created_checkpoint_sequence,
            ),
        )
        stored = replace(event, id=event_id)
        self.sources.save_source_refs(connection, "event", event_id, event.source_refs)
        return stored

    def _save_description(
        self,
        connection: Any,
        description: PersistentDescription,
    ) -> PersistentDescription:
        event_id = _required_ref(description.event_id, "description.event_id")
        description_id = description.id or new_persistent_id("description")
        connection.execute(
            """
            INSERT INTO memory_descriptions (
                id, event_id, user_id, session_id, content, description_type,
                confidence, importance, metadata, created_turn_id,
                created_checkpoint_id, created_checkpoint_sequence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                event_id = EXCLUDED.event_id,
                user_id = EXCLUDED.user_id,
                session_id = EXCLUDED.session_id,
                content = EXCLUDED.content,
                description_type = EXCLUDED.description_type,
                confidence = EXCLUDED.confidence,
                importance = EXCLUDED.importance,
                metadata = EXCLUDED.metadata,
                created_turn_id = EXCLUDED.created_turn_id,
                created_checkpoint_id = EXCLUDED.created_checkpoint_id,
                created_checkpoint_sequence = EXCLUDED.created_checkpoint_sequence,
                updated_at = NOW()
            """,
            (
                description_id,
                event_id,
                description.user_id,
                description.session_id,
                description.content,
                description.description_type,
                description.confidence,
                description.importance,
                Jsonb(dict(description.metadata)),
                description.created_turn_id,
                description.created_checkpoint_id,
                description.created_checkpoint_sequence,
            ),
        )
        stored = replace(description, id=description_id, event_id=event_id)
        self.sources.save_source_refs(
            connection,
            "description",
            description_id,
            description.source_refs,
        )
        return stored

    def _save_entity(
        self,
        connection: Any,
        entity: PersistentEntity,
    ) -> PersistentEntity:
        entity_id = entity.id or new_persistent_id("entity")
        connection.execute(
            """
            INSERT INTO memory_entities (
                id, user_id, session_id, scope, name, entity_type,
                identity_summary, aliases, confidence, importance, metadata,
                created_turn_id, created_checkpoint_id, created_checkpoint_sequence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                session_id = EXCLUDED.session_id,
                scope = EXCLUDED.scope,
                name = EXCLUDED.name,
                entity_type = EXCLUDED.entity_type,
                identity_summary = EXCLUDED.identity_summary,
                aliases = EXCLUDED.aliases,
                confidence = EXCLUDED.confidence,
                importance = EXCLUDED.importance,
                metadata = EXCLUDED.metadata,
                created_turn_id = EXCLUDED.created_turn_id,
                created_checkpoint_id = EXCLUDED.created_checkpoint_id,
                created_checkpoint_sequence = EXCLUDED.created_checkpoint_sequence,
                updated_at = NOW()
            """,
            (
                entity_id,
                entity.user_id,
                entity.session_id,
                entity.scope,
                entity.name,
                entity.entity_type,
                entity.identity_summary,
                Jsonb(list(entity.aliases)),
                entity.confidence,
                entity.importance,
                Jsonb(dict(entity.metadata)),
                entity.created_turn_id,
                entity.created_checkpoint_id,
                entity.created_checkpoint_sequence,
            ),
        )
        stored = replace(entity, id=entity_id)
        self.sources.save_source_refs(connection, "entity", entity_id, entity.source_refs)
        return stored

    def _save_property(
        self,
        connection: Any,
        memory_property: PersistentProperty,
    ) -> PersistentProperty:
        entity_id = _required_ref(memory_property.entity_id, "property.entity_id")
        property_id = memory_property.id or new_persistent_id("property")
        connection.execute(
            """
            INSERT INTO memory_properties (
                id, entity_id, user_id, session_id, content, property_type,
                confidence, importance, metadata, created_turn_id,
                created_checkpoint_id, created_checkpoint_sequence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                entity_id = EXCLUDED.entity_id,
                user_id = EXCLUDED.user_id,
                session_id = EXCLUDED.session_id,
                content = EXCLUDED.content,
                property_type = EXCLUDED.property_type,
                confidence = EXCLUDED.confidence,
                importance = EXCLUDED.importance,
                metadata = EXCLUDED.metadata,
                created_turn_id = EXCLUDED.created_turn_id,
                created_checkpoint_id = EXCLUDED.created_checkpoint_id,
                created_checkpoint_sequence = EXCLUDED.created_checkpoint_sequence,
                updated_at = NOW()
            """,
            (
                property_id,
                entity_id,
                memory_property.user_id,
                memory_property.session_id,
                memory_property.content,
                memory_property.property_type,
                memory_property.confidence,
                memory_property.importance,
                Jsonb(dict(memory_property.metadata)),
                memory_property.created_turn_id,
                memory_property.created_checkpoint_id,
                memory_property.created_checkpoint_sequence,
            ),
        )
        stored = replace(memory_property, id=property_id, entity_id=entity_id)
        self.sources.save_source_refs(
            connection,
            "property",
            property_id,
            memory_property.source_refs,
        )
        return stored

    def _save_link(
        self,
        connection: Any,
        link: PersistentLink,
    ) -> PersistentLink:
        link_id = link.id or new_persistent_id("link")
        row = connection.execute(
            """
            INSERT INTO memory_links (
                id, user_id, from_type, from_id, to_type, to_id,
                relation_type, reason, confidence, metadata, created_turn_id,
                created_checkpoint_id, created_checkpoint_sequence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (from_type, from_id, to_type, to_id, relation_type)
            DO UPDATE SET
                user_id = EXCLUDED.user_id,
                reason = EXCLUDED.reason,
                confidence = EXCLUDED.confidence,
                metadata = EXCLUDED.metadata,
                created_turn_id = EXCLUDED.created_turn_id,
                created_checkpoint_id = EXCLUDED.created_checkpoint_id,
                created_checkpoint_sequence = EXCLUDED.created_checkpoint_sequence,
                updated_at = NOW()
            RETURNING id
            """,
            (
                link_id,
                _metadata_string(link.metadata, "user_id"),
                link.from_ref.object_type,
                link.from_ref.object_id,
                link.to_ref.object_type,
                link.to_ref.object_id,
                link.relation_type,
                link.reason,
                link.confidence,
                Jsonb(dict(link.metadata)),
                link.created_turn_id,
                link.created_checkpoint_id,
                link.created_checkpoint_sequence,
            ),
        ).fetchone()
        stored_id = row["id"]
        stored = replace(link, id=stored_id)
        self.sources.save_source_refs(connection, "link", stored_id, link.source_refs)
        return stored

    def _save_time_ref(
        self,
        connection: Any,
        time_ref: PersistentTimeRef,
    ) -> PersistentTimeRef:
        time_ref_id = time_ref.id or new_persistent_id("time_ref")
        connection.execute(
            """
            INSERT INTO memory_time_refs (
                id, raw_text, time_kind, timeline_kind, certainty,
                anchor_timezone, anchor_utc_offset, anchor_message_id,
                resolved_start, resolved_end, granularity, description,
                duration_text, recurrence_text, metadata, created_turn_id,
                created_checkpoint_id, created_checkpoint_sequence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                recurrence_text = EXCLUDED.recurrence_text,
                metadata = EXCLUDED.metadata,
                created_turn_id = EXCLUDED.created_turn_id,
                created_checkpoint_id = EXCLUDED.created_checkpoint_id,
                created_checkpoint_sequence = EXCLUDED.created_checkpoint_sequence,
                updated_at = NOW()
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
                Jsonb(dict(time_ref.metadata)),
                time_ref.created_turn_id,
                time_ref.created_checkpoint_id,
                time_ref.created_checkpoint_sequence,
            ),
        )
        stored = replace(time_ref, id=time_ref_id)
        self.sources.save_source_refs(
            connection,
            "time_ref",
            time_ref_id,
            time_ref.source_refs,
        )
        return stored

    def _save_time_link(
        self,
        connection: Any,
        time_link: PersistentTimeLink,
    ) -> PersistentTimeLink:
        time_link_id = time_link.id or new_persistent_id("time_link")
        row = connection.execute(
            """
            INSERT INTO memory_time_links (
                id, target_type, target_id, time_ref_id, time_role,
                confidence, metadata, created_turn_id, created_checkpoint_id,
                created_checkpoint_sequence
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (target_type, target_id, time_ref_id, time_role)
            DO UPDATE SET
                confidence = EXCLUDED.confidence,
                metadata = EXCLUDED.metadata,
                created_turn_id = EXCLUDED.created_turn_id,
                created_checkpoint_id = EXCLUDED.created_checkpoint_id,
                created_checkpoint_sequence = EXCLUDED.created_checkpoint_sequence,
                updated_at = NOW()
            RETURNING id
            """,
            (
                time_link_id,
                time_link.target_ref.object_type,
                time_link.target_ref.object_id,
                time_link.time_ref_id,
                time_link.time_role,
                time_link.confidence,
                Jsonb(dict(time_link.metadata)),
                time_link.created_turn_id,
                time_link.created_checkpoint_id,
                time_link.created_checkpoint_sequence,
            ),
        ).fetchone()
        stored_id = row["id"]
        stored = replace(time_link, id=stored_id)
        self.sources.save_source_refs(
            connection,
            "time_link",
            stored_id,
            time_link.source_refs,
        )
        return stored


def _required_ref(value: str | None, name: str) -> str:
    if not value:
        raise ValueError(f"{name} is required")
    return value


def _metadata_string(metadata: dict[str, object], key: str) -> str | None:
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _compact_ids(values: Sequence[str]) -> list[str]:
    return [value for value in values if value]


def _placeholders(values: Sequence[object]) -> str:
    return ", ".join(["%s"] * len(values))
