"""DTOs and repository boundaries for durable memory persistence."""

from .interfaces import PersistentMemoryRepository

from .models import (
    Confidence,
    Importance,
    ObjectType,
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
    TimeCertainty,
    TimeKind,
    TimelineKind,
)
from .runtime import (
    MemoryRecordPersistenceAdapter,
    MemoryWriteResultPersistenceSync,
    PersistentMemoryBuildResult,
    PersistentMemorySkippedRecord,
    PersistentMemorySyncResult,
)

__all__ = [
    "Confidence",
    "Importance",
    "MemoryRecordPersistenceAdapter",
    "MemoryWriteResultPersistenceSync",
    "ObjectType",
    "PersistentDescription",
    "PersistentEntity",
    "PersistentEvent",
    "PersistentLink",
    "PersistentMemoryBundle",
    "PersistentMemoryBuildResult",
    "PersistentMemoryRepository",
    "PersistentMemorySkippedRecord",
    "PersistentObjectRef",
    "PersistentProperty",
    "PersistentSourceRef",
    "PersistentTimeLink",
    "PersistentTimeRef",
    "PersistentMemorySyncResult",
    "TimeCertainty",
    "TimeKind",
    "TimelineKind",
]
