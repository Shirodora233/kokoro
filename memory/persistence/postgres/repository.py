"""PostgreSQL repository for normalized durable memory objects."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Mapping, Sequence

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

LOGGER = logging.getLogger(__name__)


class PostgresPersistentMemoryRepository(PersistentMemoryRepository):
    """Repository for normalized memory tables backed by memory_objects."""

    def __init__(
        self,
        database_url: str | None = None,
        database: PostgresPersistentMemoryDatabase | None = None,
        ensure_schema: bool = True,
        embedding_service: object | None = None,
    ) -> None:
        if database is None:
            if database_url is None:
                raise ValueError("database_url is required")
            database = PostgresPersistentMemoryDatabase(database_url)
        self.database = database
        self.sources = PostgresMemorySourceRepository()
        self.embedding_service = embedding_service
        if ensure_schema:
            self.ensure_schema()

    def ensure_schema(self) -> None:
        self.database.ensure_schema()

    def save_bundle(self, bundle: PersistentMemoryBundle) -> PersistentMemoryBundle:
        with self.database.connect() as connection:
            result = self.save_bundle_in_connection(connection, bundle)
        self._maybe_generate_embeddings(result)
        return result

    def _maybe_generate_embeddings(
        self,
        bundle: PersistentMemoryBundle,
    ) -> None:
        if self.embedding_service is None:
            return
        try:
            with self.database.connect() as connection:
                self.embedding_service.embed_bundle(connection, bundle)
        except Exception:
            LOGGER.warning(
                "Embedding generation failed for bundle — memory write unaffected",
                exc_info=True,
            )

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

    def get_event(self, event_id: str) -> PersistentEvent | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_EVENT_SELECT} WHERE e.id = %s",
                (event_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, event_id)
        return event_from_row(row, source_refs)

    def get_description(self, description_id: str) -> PersistentDescription | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_DESCRIPTION_SELECT} WHERE d.id = %s",
                (description_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, description_id)
        return description_from_row(row, source_refs)

    def get_entity(self, entity_id: str) -> PersistentEntity | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_ENTITY_SELECT} WHERE ent.id = %s GROUP BY ent.id, o.id, cp.sequence",
                (entity_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, entity_id)
        return entity_from_row(row, source_refs)

    def get_property(self, property_id: str) -> PersistentProperty | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_PROPERTY_SELECT} WHERE p.id = %s",
                (property_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, property_id)
        return property_from_row(row, source_refs)

    def get_link(self, link_id: str) -> PersistentLink | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_RELATION_SELECT} WHERE r.id = %s",
                (link_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, link_id)
        return link_from_row(row, source_refs)

    def get_time_ref(self, time_ref_id: str) -> PersistentTimeRef | None:
        with self.database.connect() as connection:
            row = connection.execute(
                f"{_TIME_REF_SELECT} WHERE tr.id = %s",
                (time_ref_id,),
            ).fetchone()
            if not row:
                return None
            source_refs = self.sources.load_source_refs(connection, time_ref_id)
        return time_ref_from_row(row, source_refs)

    def get_time_link(self, time_link_id: str) -> PersistentTimeLink | None:
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
    ) -> list[PersistentEvent]:
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
    ) -> list[PersistentEntity]:
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
        visible_session_scopes: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[PersistentDescription]:
        conditions = ["o.status = 'active'"]
        params: list[object] = []
        ids = _compact_ids(event_ids) if event_ids is not None else None
        if ids is not None:
            if not ids:
                return []
            conditions.append(f"d.event_id IN ({_placeholders(ids)})")
            params.extend(ids)
            if user_id is not None or session_id is not None:
                scope_conditions, scope_params = _object_scope_conditions(
                    user_id,
                    session_id,
                    visible_session_scopes=visible_session_scopes,
                )
                conditions.extend(scope_conditions)
                params.extend(scope_params)
        else:
            scope_conditions, scope_params = _object_scope_conditions(
                user_id,
                session_id,
                visible_session_scopes=visible_session_scopes,
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
        visible_session_scopes: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[PersistentProperty]:
        conditions = ["o.status = 'active'"]
        params: list[object] = []
        ids = _compact_ids(entity_ids) if entity_ids is not None else None
        if ids is not None:
            if not ids:
                return []
            conditions.append(f"p.entity_id IN ({_placeholders(ids)})")
            params.extend(ids)
            if user_id is not None or session_id is not None:
                scope_conditions, scope_params = _object_scope_conditions(
                    user_id,
                    session_id,
                    visible_session_scopes=visible_session_scopes,
                )
                conditions.extend(scope_conditions)
                params.extend(scope_params)
        else:
            scope_conditions, scope_params = _object_scope_conditions(
                user_id,
                session_id,
                visible_session_scopes=visible_session_scopes,
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
        session_id: str | None = None,
        visible_session_scopes: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[PersistentLink]:
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
        if user_id is not None or session_id is not None:
            scope_conditions, scope_params = _object_scope_conditions(
                user_id,
                session_id,
                visible_session_scopes=visible_session_scopes,
            )
            conditions.extend(scope_conditions)
            params.extend(scope_params)
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
        user_id: str | None = None,
        session_id: str | None = None,
        visible_session_scopes: Sequence[Mapping[str, Any]] | None = None,
    ) -> list[PersistentTimeLink]:
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
        if user_id is not None or session_id is not None:
            scope_conditions, scope_params = _object_scope_conditions(
                user_id,
                session_id,
                visible_session_scopes=visible_session_scopes,
            )
            conditions.extend(scope_conditions)
            params.extend(scope_params)
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

    def get_time_refs(
        self,
        time_ref_ids: Sequence[str],
    ) -> list[PersistentTimeRef]:
        ids = _compact_ids(time_ref_ids)
        if not ids:
            return []
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

    # ----------------------------------------------------------------
    # User-facing memory management
    # ----------------------------------------------------------------

    def list_user_memories(
        self,
        user_id: str,
        memory_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List active memory objects for a user (for user-facing CRUD)."""
        type_condition = ""
        params: list[object] = [user_id]
        if memory_type and memory_type in {
            "event", "entity", "description", "property",
        }:
            type_condition = "AND o.object_type = %s"
            params.append(memory_type)
        with self.database.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT o.id, o.object_type, o.user_id, o.session_id,
                       o.status, o.confidence, o.importance,
                       o.created_at, o.updated_at, o.metadata
                FROM memory_objects o
                WHERE o.user_id = %s
                  AND o.status = 'active'
                  {type_condition}
                ORDER BY o.updated_at DESC, o.id ASC
                LIMIT %s
                """,
                (*params, max(0, limit)),
            ).fetchall()
        return [_user_memory_dict(row) for row in rows]

    def get_user_memory_detail(
        self,
        object_id: str,
    ) -> dict[str, Any] | None:
        """Get detail for a single memory object with source refs."""
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT o.id, o.object_type, o.user_id, o.session_id,
                       o.status, o.confidence, o.importance,
                       o.created_at, o.updated_at, o.metadata
                FROM memory_objects o
                WHERE o.id = %s AND o.status = 'active'
                """,
                (object_id,),
            ).fetchone()
            if not row:
                return None
            result = _user_memory_dict(row)
            sources = self.sources.load_source_refs(connection, object_id)
            result["source_refs"] = [
                {
                    "source_type": s.source_type,
                    "source_id": s.source_id,
                    "quote": s.quote,
                }
                for s in sources
            ]
            # Add content from the type-specific table
            content = self._load_memory_content(connection, row["object_type"], object_id)
            if content:
                result["content"] = content
            return result

    def forget_memory(self, object_id: str) -> bool:
        """Tombstone a single memory object by id."""
        with self.database.connect() as connection:
            result = connection.execute(
                """
                UPDATE memory_objects
                SET status = 'deleted',
                    deleted_at = NOW(),
                    deleted_reason = 'user_requested',
                    updated_at = NOW()
                WHERE id = %s AND status = 'active'
                """,
                (object_id,),
            )
            if result.rowcount > 0:
                connection.execute(
                    """
                    DELETE FROM memory_object_embeddings
                    WHERE object_id = %s
                    """,
                    (object_id,),
                )
            return result.rowcount > 0

    @staticmethod
    def _load_memory_content(
        connection: Any,
        object_type: str,
        object_id: str,
    ) -> dict[str, Any] | None:
        """Load type-specific content for a memory object."""
        if object_type == "event":
            row = connection.execute(
                "SELECT title, summary, event_type FROM memory_events WHERE id = %s",
                (object_id,),
            ).fetchone()
            if row:
                return {"title": row["title"], "summary": row["summary"], "event_type": row["event_type"]}
        elif object_type == "entity":
            row = connection.execute(
                "SELECT name, entity_type, identity_summary FROM memory_entities WHERE id = %s",
                (object_id,),
            ).fetchone()
            if row:
                return {"name": row["name"], "entity_type": row["entity_type"], "identity_summary": row["identity_summary"]}
        elif object_type == "description":
            row = connection.execute(
                "SELECT content, description_type FROM memory_descriptions WHERE id = %s",
                (object_id,),
            ).fetchone()
            if row:
                return {"content": row["content"], "description_type": row["description_type"]}
        elif object_type == "property":
            row = connection.execute(
                "SELECT content, property_type FROM memory_properties WHERE id = %s",
                (object_id,),
            ).fetchone()
            if row:
                return {"content": row["content"], "property_type": row["property_type"]}
        return None

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
        return stored

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
                created_turn_id = EXCLUDED.created_turn_id,
                created_checkpoint_id = EXCLUDED.created_checkpoint_id,
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

    def tombstone_by_session_id(
        self,
        session_id: str,
        *,
        deleted_reason: str = "session_deleted",
    ) -> int:
        """Soft-delete active memory objects for a session and their embeddings."""
        with self.database.connect() as connection:
            # Delete embeddings first (FK to memory_objects)
            connection.execute(
                """
                DELETE FROM memory_object_embeddings
                WHERE object_id IN (
                    SELECT id FROM memory_objects
                    WHERE session_id = %s AND status = 'active'
                )
                """,
                (session_id,),
            )
            # Tombstone memory objects
            result = connection.execute(
                """
                UPDATE memory_objects
                SET status = 'deleted',
                    deleted_at = NOW(),
                    deleted_reason = %s,
                    updated_at = NOW()
                WHERE session_id = %s
                  AND status = 'active'
                """,
                (deleted_reason, session_id),
            )
            return result.rowcount

    def tombstone_by_user_id(
        self,
        user_id: str,
        *,
        deleted_reason: str = "user_deleted",
    ) -> int:
        """Soft-delete active memory objects for a user and their embeddings."""
        with self.database.connect() as connection:
            connection.execute(
                """
                DELETE FROM memory_object_embeddings
                WHERE object_id IN (
                    SELECT id FROM memory_objects
                    WHERE user_id = %s AND status = 'active'
                )
                """,
                (user_id,),
            )
            result = connection.execute(
                """
                UPDATE memory_objects
                SET status = 'deleted',
                    deleted_at = NOW(),
                    deleted_reason = %s,
                    updated_at = NOW()
                WHERE user_id = %s
                  AND status = 'active'
                """,
                (deleted_reason, user_id),
            )
            return result.rowcount

    def delete_all_memory(self) -> dict[str, int]:
        """Hard-delete all memory data (objects, embeddings, source refs)."""
        with self.database.connect() as connection:
            embeddings = connection.execute(
                "DELETE FROM memory_object_embeddings"
            ).rowcount
            sources = connection.execute(
                "DELETE FROM memory_sources"
            ).rowcount
            objects_result = connection.execute(
                "DELETE FROM memory_objects"
            ).rowcount
            # Also clean up sub-tables that reference memory_objects
            connection.execute("DELETE FROM memory_entity_aliases")
            connection.execute("DELETE FROM memory_events")
            connection.execute("DELETE FROM memory_entities")
            connection.execute("DELETE FROM memory_descriptions")
            connection.execute("DELETE FROM memory_properties")
            connection.execute("DELETE FROM memory_relations")
            connection.execute("DELETE FROM memory_time_refs")
            connection.execute("DELETE FROM memory_time_links")
        return {
            "memory_objects": objects_result,
            "memory_object_embeddings": embeddings,
            "memory_sources": sources,
        }


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


def _user_memory_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    """Convert a memory_objects row to a user-facing dict."""
    result: dict[str, Any] = {
        "id": row["id"],
        "object_type": row["object_type"],
        "user_id": row["user_id"],
        "session_id": row["session_id"],
        "status": row["status"],
        "confidence": row["confidence"],
        "importance": row["importance"],
    }
    created_at = row.get("created_at")
    if created_at is not None:
        result["created_at"] = str(created_at)
    updated_at = row.get("updated_at")
    if updated_at is not None:
        result["updated_at"] = str(updated_at)
    metadata = row.get("metadata")
    if isinstance(metadata, Mapping):
        result["metadata"] = dict(metadata)
    return result


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
    *,
    visible_session_scopes: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[str], list[object]]:
    conditions: list[str] = []
    params: list[object] = []
    visible_scopes = [
        scope for scope in visible_session_scopes or []
        if isinstance(scope, Mapping)
    ]
    if user_id is not None or session_id is not None:
        conditions.append("(o.user_id IS NULL OR o.user_id = %s)")
        params.append(user_id)
        if visible_scopes:
            session_conditions = ["o.session_id IS NULL"]
            for scope in visible_scopes:
                scoped_session_id = scope.get("session_id")
                max_sequence = scope.get("max_checkpoint_sequence")
                if not isinstance(scoped_session_id, str):
                    continue
                if isinstance(max_sequence, int):
                    session_conditions.append(
                        """
                        (
                          o.session_id = %s
                          AND (
                            o.created_checkpoint_id IS NULL
                            OR cp.sequence <= %s
                          )
                        )
                        """
                    )
                    params.extend([scoped_session_id, max_sequence])
                else:
                    session_conditions.append("o.session_id = %s")
                    params.append(scoped_session_id)
            conditions.append("(" + " OR ".join(session_conditions) + ")")
        else:
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
