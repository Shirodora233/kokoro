"""Provider-neutral LLM interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict


class ChatMessageParam(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class ChatCompletionResult:
    content: str
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    provider_message_id: str | None = None


class ChatClient(Protocol):
    def complete(
        self,
        messages: list[ChatMessageParam],
        model: str | None = None,
        temperature: float | None = None,
    ) -> ChatCompletionResult:
        """Generate one assistant message from normalized chat messages."""


class EmbeddingClient(Protocol):
    """Generate embedding vectors for input texts."""

    def embed(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[list[float]]:
        """Return embedding vectors, one per input text."""
        ...
