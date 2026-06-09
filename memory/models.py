"""Provider-neutral data contracts for the memory system."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

MessageRole = Literal["system", "user", "assistant"]
MemoryContextKind = Literal[
    "long_term_memory",
    "session_memory",
    "session_summary",
    "retrieval_hint",
]
ContextActionType = Literal[
    "summarize_range",
    "set_context_start",
    "pin_messages",
]
MemoryRecordType = Literal[
    "event",
    "description",
    "entity",
    "property",
    "relation",
    "link",
    "time_ref",
    "time_link",
    "summary",
]
MemoryObjectType = Literal[
    "event",
    "description",
    "entity",
    "property",
    "link",
    "time_ref",
    "time_link",
    "message",
    "message_section",
    "summary",
]


@dataclass(frozen=True)
class MemoryInputMessage:
    """Conversation-neutral message passed into memory processing."""

    id: str
    role: MessageRole
    content: str
    session_id: str | None = None
    user_id: str | None = None
    created_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ConversationContextState:
    """The conversation-owned context window state visible to memory."""

    context_start_index: int
    total_messages: int
    max_context_messages: int | None = None
    active_message_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemorySourceRef:
    """Reference to source material supporting a memory object."""

    source_type: str
    source_id: str
    quote: str | None = None
    span_start: int | None = None
    span_end: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryRecord:
    """Generic memory record envelope used at interface boundaries."""

    id: str | None
    memory_type: MemoryRecordType
    text: str
    source_refs: list[MemorySourceRef] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryObjectRef:
    """Provider-neutral reference to a memory object."""

    object_type: MemoryObjectType
    object_id: str

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemorySearchRequest:
    """Request for the one search snapshot shared by a memory turn."""

    user_id: str | None = None
    session_id: str | None = None
    query: str | None = None
    timezone: str | None = None
    candidates: list[MemoryRecord] = field(default_factory=list)
    active_memory_context: "ActiveMemoryContext | None" = None
    limit: int = 20
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemorySearchHit:
    """One recalled memory object before downstream hydration or matching."""

    object_ref: MemoryObjectRef
    score: float
    reason: str
    matched_text: str | None = None
    record: MemoryRecord | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemorySearchResult:
    """Shared search result used for prompt context and reconciliation."""

    hits: list[MemorySearchHit] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ActiveMemoryContext:
    """Recently mentioned memories relevant to the active conversation context."""

    event_memories: list[MemoryRecord] = field(default_factory=list)
    entity_memories: list[MemoryRecord] = field(default_factory=list)
    property_memories: list[MemoryRecord] = field(default_factory=list)
    other_memories: list[MemoryRecord] = field(default_factory=list)
    last_refreshed_at_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryContextBlock:
    """A block of memory context that conversation may inject into an LLM prompt."""

    content: str
    kind: MemoryContextKind = "long_term_memory"
    source_memory_ids: list[str] = field(default_factory=list)
    priority: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContextAction:
    """Memory's recommendation for conversation-owned context maintenance."""

    action_type: ContextActionType
    reason: str
    start_message_id: str | None = None
    end_message_id: str | None = None
    target_message_id: str | None = None
    message_ids: list[str] = field(default_factory=list)
    summary_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryTurnInput:
    """Input for memory processing after conversation receives a new message."""

    user_id: str | None
    session_id: str | None
    new_message: MemoryInputMessage
    timezone: str | None = None
    conversation_context: list[MemoryInputMessage] = field(default_factory=list)
    context_state: ConversationContextState | None = None
    active_memory_context: ActiveMemoryContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryTurnResult:
    """Output returned from memory processing to conversation."""

    memory_context: list[MemoryContextBlock] = field(default_factory=list)
    context_actions: list[ContextAction] = field(default_factory=list)
    created_memories: list[MemoryRecord] = field(default_factory=list)
    updated_memories: list[MemoryRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryTurnSnapshot:
    """Prepared turn state reused before and after the LLM response."""

    turn: MemoryTurnInput
    candidates: list[MemoryRecord] = field(default_factory=list)
    search_result: MemorySearchResult = field(default_factory=MemorySearchResult)
    memory_context: list[MemoryContextBlock] = field(default_factory=list)
    retrieved_memories: list[MemoryRecord] = field(default_factory=list)
    active_memory_context: ActiveMemoryContext | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryTurnPrepareResult:
    """Prepared memory state returned before an LLM response is generated."""

    snapshot: MemoryTurnSnapshot
    memory_context: list[MemoryContextBlock] = field(default_factory=list)
    context_actions: list[ContextAction] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryTurnCommitInput:
    """Input for committing a prepared turn after the assistant responds."""

    snapshot: MemoryTurnSnapshot
    assistant_message: MemoryInputMessage | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryRetrievalRequest:
    """Request for memory context outside the normal turn-processing flow."""

    user_id: str | None = None
    session_id: str | None = None
    query: str | None = None
    timezone: str | None = None
    conversation_context: list[MemoryInputMessage] = field(default_factory=list)
    active_memory_context: ActiveMemoryContext | None = None
    limit: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MemoryRetrievalResult:
    """Memory context returned for a retrieval request."""

    memory_context: list[MemoryContextBlock] = field(default_factory=list)
    records: list[MemoryRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return asdict(self)
