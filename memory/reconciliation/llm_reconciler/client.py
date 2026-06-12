"""LLM call wrapper for reconciliation."""

from __future__ import annotations

from collections.abc import Sequence

from llm.interfaces import ChatClient, ChatMessageParam

from ..models import MemoryReconciliationRequest
from .models import LLMReconciliationCallResult
from .prompt import LLMReconciliationPromptBuilder


class LLMReconciliationClient:
    """Call a chat model for reconciliation decisions."""

    def __init__(
        self,
        chat_client: ChatClient,
        model: str | None = None,
        temperature: float = 0.0,
        prompt_builder: LLMReconciliationPromptBuilder | None = None,
    ) -> None:
        self.chat_client = chat_client
        self.model = model
        self.temperature = temperature
        self.prompt_builder = prompt_builder or LLMReconciliationPromptBuilder()

    def reconcile(
        self,
        request: MemoryReconciliationRequest,
    ) -> LLMReconciliationCallResult:
        prompt_messages = self.prompt_builder.build(request)
        return self._complete(prompt_messages)

    def repair(
        self,
        request: MemoryReconciliationRequest,
        previous_output: str,
        errors: Sequence[str],
    ) -> LLMReconciliationCallResult:
        prompt_messages = self.prompt_builder.build_repair(
            request,
            previous_output,
            errors,
        )
        return self._complete(prompt_messages)

    def _complete(
        self,
        prompt_messages: list[ChatMessageParam],
    ) -> LLMReconciliationCallResult:
        completion = self.chat_client.complete(
            prompt_messages,
            model=self.model,
            temperature=self.temperature,
        )
        return LLMReconciliationCallResult(
            prompt_messages=prompt_messages,
            raw_output=completion.content,
            model=completion.model,
            usage=dict(completion.usage),
            provider_message_id=completion.provider_message_id,
        )
