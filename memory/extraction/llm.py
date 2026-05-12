"""LLM caller for memory extraction."""

from __future__ import annotations

from llm.interfaces import ChatClient

from .prompt import MemoryExtractionPromptBuilder
from ..models import MemoryTurnInput


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
        completion = self.chat_client.complete(
            self.prompt_builder.build(turn),
            model=self.model,
            temperature=self.temperature,
        )
        return completion.content
