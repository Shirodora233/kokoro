"""LLM caller for memory extraction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from llm.interfaces import ChatMessageParam
from llm.interfaces import ChatClient

from .prompt import MemoryExtractionPromptBuilder
from ..models import MemoryTurnInput


@dataclass(frozen=True)
class LLMMemoryExtractionCallResult:
    """Structured LLM extraction call result used by debug tracing."""

    prompt_messages: list[ChatMessageParam]
    raw_output: str
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    provider_message_id: str | None = None


class LLMMemoryExtractionClient:
    """Call a chat model and return the raw extraction response."""

    def __init__(
        self,
        chat_client: ChatClient,
        model: str | None = None,
        temperature: float = 0.0,
        prompt_builder: MemoryExtractionPromptBuilder | None = None,
    ) -> None:
        self.chat_client = chat_client
        self.model = model
        self.temperature = temperature
        self.prompt_builder = prompt_builder or MemoryExtractionPromptBuilder()

    def extract_text(self, turn: MemoryTurnInput) -> str:
        return self.extract(turn).raw_output

    def extract(self, turn: MemoryTurnInput) -> LLMMemoryExtractionCallResult:
        prompt_messages = self.prompt_builder.build(turn)
        completion = self.chat_client.complete(
            prompt_messages,
            model=self.model,
            temperature=self.temperature,
        )
        return LLMMemoryExtractionCallResult(
            prompt_messages=prompt_messages,
            raw_output=completion.content,
            model=completion.model,
            usage=dict(completion.usage),
            provider_message_id=completion.provider_message_id,
        )
